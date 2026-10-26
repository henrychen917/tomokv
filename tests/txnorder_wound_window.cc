// AT4-WOUND-1: deterministic production owner turns, no timing assumptions.
#define main survivors_fixture_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace {
void group_window(Server& server, const Config& cfg, bool oom) {
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

    if (oom) {
        // Fail inside watch_place_unit itself, after claim construction. This
        // cannot accidentally exercise txn_group_arrive's separate OOM path.
        Shard::WatchReservation claim{&state, &state.epoch, &state.aborted,
            &state.watch_refs, nullptr, 0, false, true};
        claim.unit_kind = 2;
        allocation_failed = false;
        fail_new_after = 0;
        require(server.shard(0).watch_place_unit(state.group_attempt()->claims[0], claim),
                "allocation failure completes placement as an error");
        fail_new_after = -1;
        require(allocation_failed && state.aborted.load(), "placement allocation really failed");
    } else {
    // Suspend a foreign txn_wound immediately after its FIRST CAS. This is
    // exactly the existing Placing -> Wounded transition; the epoch CAS and
    // aborted store have not executed yet. The other owner may still run.
    TxnPhase placing = TxnPhase::Placing;
    require(state.group_attempt()->phase.compare_exchange_strong(
                placing, TxnPhase::Wounded, std::memory_order_acq_rel),
            "foreign wound wins the phase CAS");
    require(state.epoch.load() == 0 && !state.aborted.load(),
            "paused wound has not published cancellation");
    }
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
    const bool valid = oom
        ? read == TxnGroupRead::Done && terminal && source_present &&
          state.final_reply == FinalReply::Work && state.final_error == WorkError::Oom &&
          before == 0 && accepted
        : read == TxnGroupRead::Done && before == kAtomicCancelledEpoch && aborted &&
          source_present && !accepted && state.epoch.load() == kAtomicCancelledEpoch;
    // The production commit flush retries only the cancelled-epoch case.
    // Here it would take the terminal aborted arm with an unmaterialized image.
    state.aborted.store(true);
    for (uint32_t i = 0; i < 2; ++i)
        xshard_cleanup_shard_at(server.shard(i), UINT64_MAX, UINT64_MAX, 256);
    require(txn_group_release(state), "diagnostic releases every sidecar pin");
    release_records(server);
    if (escaped || !valid) {
        std::fputs("FAIL: wounded group completed before cancellation publication; commit accepted\n", stderr);
        std::exit(1);
    }
    std::puts(oom ? "PASS: placement allocation failure reports OOM"
                  : "PASS: wounded group cannot escape through a terminal commit");
}

void exec_window(Server& server) {
    Client client{-1}; client.set_id(811);
    const auto a = key_on(server, 0, "exec-window-a"), b = key_on(server, 1, "exec-window-b");
    require(local(server, {"SET", a, "before"}) == "+OK\r\n", "EXEC source seeded");
    require(multi_io(server, client, {"MULTI"}) == "+OK\r\n", "MULTI starts");
    require(multi_io(server, client, {"SET", a, "after"}) == "+QUEUED\r\n", "write queued");
    require(multi_io(server, client, {"GET", b}) == "+QUEUED\r\n", "remote read queued");
    Request request({"EXEC"}); MultiExecState* state = nullptr;
    require(multi_handle_io(server, client, request.op, 0, state) == MultiIoAction::Dispatch && state,
            "EXEC prepared");
    initialize_multi_owner_record_refs(*state);
    multi_dispatch_started(client, state);
    auto* carrier = client.rob().acquire(); require(carrier, "EXEC carrier");
    carrier->spec = request.op.spec;
    require(!execute_watch_phase(*state, server.shard(0)), "first arrival waits");
    require(execute_watch_phase(*state, server.shard(1)), "remote placement completes");
    require(state->watch_pending.load() == 1, "last placement held");
    TxnPhase placing = TxnPhase::Placing;
    require(state->decision.phase.compare_exchange_strong(placing, TxnPhase::Wounded),
            "foreign wound wins phase before epoch");
    require(state->decision.epoch.load() == 0 && !state->decision.aborted.load(),
            "EXEC cancellation gap is open");
    require(execute_watch_phase(*state, server.shard(0)), "last placement observes wound");
    bool done[16]{}; bool final = false;
    for (unsigned turn = 0; turn < 64 && state->tasks_pending.load(); ++turn)
        for (int sid : state->shards) if (!done[sid]) {
            const auto result = multi_execute_task(server, multi_make_task(&client, 0, sid, state),
                server.shard(sid), server.worker_of_shard(sid), 0, nullptr);
            final |= result == MultiTaskResult::Final;
            done[sid] = !multi_task_retry(result);
        }
    require(state->tasks_pending.load() == 0 && state->finalized.load(), "EXEC finalizer ran inside gap");
    std::printf("exec-window epoch=%llu doomed=%d terminal=%d retry=%d\n",
        (unsigned long long)state->decision.epoch.load(), state->doomed, final,
        server.multi_retry_lane(0).head.load() == &state->retry);
    require(!final && state->doomed && state->decision.epoch.load() == kAtomicCancelledEpoch &&
            server.multi_retry_lane(0).head.load() == &state->retry,
            "wounded EXEC must restart, never return an aborted final reply");
    require(local(server, {"GET", a}) == "$6\r\nbefore\r\n", "wound ran no write");
    auto* next = multi_rebuild_attempt(*state);
    require(next && next->attempt == state->attempt + 1 &&
            next->decision.age_ns == state->decision.age_ns &&
            next->decision.age_io == state->decision.age_io &&
            next->decision.age_seq == state->decision.age_seq, "EXEC restart retains original version");
    destroy_multi_state(next);
    server.multi_retry_lane(0).head.store(nullptr);
    release_records(server); destroy_multi_state(state);
    std::puts("PASS: wounded EXEC restarts before an aborted reply");
}
}

int main(int argc, char** argv) {
    require(argc == 3, "usage: group|exec|oom 1s|2s");
    require(command_registry_init(false), "registry initialized");
    Config cfg;
    cfg.databases = 1; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.save.clear();
    cfg.thread_mode = std::string(argv[2]) == "1s"
        ? ThreadMode::Fused : ThreadMode::Split;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "serverless owners initialized");
    command_bind_server(&server);

    const std::string name = argv[1];
    if (name == "group" || name == "oom") group_window(server, cfg, name == "oom");
    else if (name == "exec") exec_window(server);
    else require(false, "known wound-window case");
}
