// Diagnostic for an inherited wound-publication window, separate from the
// index gate. The old and new registry are both expected to expose this bug.
// No server, listener, worker, timing delay, or production mutation is used.
#define main survivors_fixture_main
#include "tests/atomic_survivors_unit.cc"
#undef main

int main(int argc, char** argv) {
    require(command_registry_init(false), "registry initialized");
    Config cfg;
    cfg.databases = 1; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.save.clear();
    cfg.thread_mode = argc > 1 && std::string(argv[1]) == "1s"
        ? ThreadMode::Fused : ThreadMode::Split;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "serverless owners initialized");
    command_bind_server(&server);
    const auto a = key_on(server, 0, "wound-window-a");
    const auto b = key_on(server, 1, "wound-window-b");
    require(local(server, {"SET", a, "present"}) == "+OK\r\n", "source really exists");
    release_records(server);
    Request request({"RENAMENX", a, b});
    ScatterState state;
    KeyRef keys[2]; ShardGroup groups[2]; uint32_t order[2]{0, 1};
    ObjectImage images[2];
    state.server = &server;
    state.atomic_group = state.atomic_apply = true;
    state.kind = Kind::Renamenx;
    state.keys = keys; state.groups = groups; state.key_order = order;
    state.images = images; state.phase = 1; state.two_hop = true;
    state.key_count = state.nsub = state.group_cap = 2;
    for (uint32_t i = 0; i < 2; ++i) {
        keys[i] = KeyRef{FlatStore::hash_key(request.op.arg(i + 1)), i + 1, int32_t(i)};
        groups[i].shard = i; groups[i].begin = i; groups[i].count = 1;
    }
    require(txn_group_prepare(state, server, 0), "group sidecar initialized");
    require(!txn_group_ready(state, server.shard(1), request.op), "destination owner awaits arrival");
    require(txn_group_arrive(state, server.shard(0), request.op), "source owner arrives");
    require(txn_group_ready(state, server.shard(1), request.op), "destination owner places");
    require(state.pending.fetch_sub(1, std::memory_order_acq_rel) == 2,
            "destination completion leaves the source outstanding");

    // Suspend a foreign txn_wound immediately after its FIRST CAS. This is
    // exactly the existing Placing -> Wounded transition; the epoch CAS and
    // aborted store have not executed yet. The other owner may still run.
    TxnPhase placing = TxnPhase::Placing;
    require(state.group_attempt()->phase.compare_exchange_strong(
                placing, TxnPhase::Wounded, std::memory_order_acq_rel),
            "foreign wound wins the phase CAS");
    require(state.epoch.load() == 0 && !state.aborted.load(),
            "paused wound has not published cancellation");
    const auto read = txn_group_read_prepare(state, server.shard(0), request.op);
    const auto before = state.epoch.load();
    const bool aborted = state.aborted.load();
    // A Done source fragment skips materialization. This is the production
    // phase-one interpreter over its still-empty image, despite a live source.
    if (read == TxnGroupRead::Done)
        require(state.pending.fetch_sub(1, std::memory_order_acq_rel) == 1,
                "skipped source is the final completion");
    const bool terminal = read == TxnGroupRead::Done && finish_phase1(state, request.op);
    const bool no_source = state.final_reply == FinalReply::NoSuchKey;
    const bool source_present = server.shard(0).store().find(keys[0].hash, slice(a)) != nullptr;
    const auto ticket = server.atomic_commit_reserve();
    const bool accepted = txn_group_decide(state, ticket);
    server.atomic_commit_publish();
    const bool escaped = read == TxnGroupRead::Done && before == 0 && aborted &&
        terminal && no_source && source_present && accepted && state.epoch.load() == ticket;
    std::printf("wound-window namespace=%s mode=%s read_done=%d pre_epoch=%llu "
                "aborted=%d no_such_key=%d source_present=%d commit_accepted=%d final_epoch=%llu\n",
        kSingleDatabase ? "db0" : "multi", cfg.thread_mode == ThreadMode::Fused ? "1s" : "2s",
        read == TxnGroupRead::Done, (unsigned long long)before, aborted, no_source, source_present, accepted,
        (unsigned long long)state.epoch.load());
    // The production commit flush retries only the cancelled-epoch case.
    // Here it would take the terminal aborted arm with an unmaterialized image.
    state.aborted.store(true);
    for (uint32_t i = 0; i < 2; ++i)
        xshard_cleanup_shard_at(server.shard(i), UINT64_MAX, UINT64_MAX, 256);
    require(txn_group_release(state), "diagnostic releases every sidecar pin");
    release_records(server);
    if (escaped) {
        std::fputs("FAIL: wounded group completed before cancellation publication; commit accepted\n", stderr);
        return 1;
    }
    std::puts("PASS: wounded group cannot escape through a terminal commit");
}
