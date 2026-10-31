// Exercise the real executor's local continuation and H3 service boundary.
#define TOMO_CORE_CONCURRENCY_TEST
#define TOMO_STORE_REGRESSION_TEST
#define main txn_chain_core_unused_main
#include "tests/core_concurrency_unit.cc"
#undef main
#define main txn_chain_atomic_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace tomo {
struct TxnChainTest {
    template <bool Fused>
    static void local_unit() {
        CoreConcurrencyTest::Fixture<Fused> f(false);
        command_bind_server(&f.server);
        std::string acl_error;
        require(acl_initialize(f.server, f.server.cfg(), acl_error), "initialize default ACL");
        Client client{-1}; f.client(client);
        const auto& owned = f.server.thread(f.source).shards();
        require(owned.size() >= 2, "two distinct shards on one owner");
        const auto a = f.key(owned[0]->id()), b = f.key(owned[1]->id());
        require(multi_io(f.server, client, {"MULTI"}) == "+OK\r\n", "open MULTI");
        require(multi_io(f.server, client, {"INCR", a}) == "+QUEUED\r\n", "queue first shard");
        require(multi_io(f.server, client, {"INCR", b}) == "+QUEUED\r\n", "queue sibling");
        Request request({"EXEC"}); MultiExecState* state = nullptr;
        require(multi_handle_io(f.server, client, request.op, f.io_id, state) == MultiIoAction::Dispatch,
                "prepare actual same-owner EXEC");
        require(state && state->shards.size() == 2, "two-fragment transaction");
        Op* carrier = client.rob().acquire(); require(carrier, "EXEC ROB slot");
        carrier->spec = request.op.spec; carrier->attach_multi_state(state);
        client.rob().publish(); multi_dispatch_started(client, state);
        auto& loop = f.loops[f.source];
        require(loop.execute(multi_make_task(&client, 0, state->shards[0], state)), "first fragment arrives");
        require(state->tasks_pending.load() == 2 && !loop.multi_retries_.empty(), "first fragment really waits");
        require(loop.execute(multi_make_task(&client, 0, state->shards[1], state)), "sibling arrives");
        require(state->tasks_pending.load() == 0 && state->finalized.load() && loop.multi_retries_.empty(),
                "all same-owner fragments finish in the sibling's owner turn, without a poll pass");
        require(carrier->state.load() == OpState::Done, "public EXEC completed");
        require(local(f.server, {"GET", a}) == "$1\r\n1\r\n" &&
                local(f.server, {"GET", b}) == "$1\r\n1\r\n", "exact transaction values");
        carrier->detach_scatter_state(); release_records(f.server); destroy_multi_state(state);
        std::puts("PASS one-turn same-owner unit");
    }

    template <bool Fused>
    static void watch_boundary() {
        CoreConcurrencyTest::Fixture<Fused> f(false);
        command_bind_server(&f.server);
        std::string acl_error;
        require(acl_initialize(f.server, f.server.cfg(), acl_error), "initialize default ACL");
        auto& loop = f.loops[f.source];
        const int sid = f.sid(); auto& shard = f.server.shard(sid);
        const auto key = f.key(sid);
        Client holder_client{-1}; f.client(holder_client); holder_client.set_id(8300);
        auto* holder = fixture_allocate_state(f.server, holder_client, f.io_id, MultiStateKind::Execute);
        require(holder, "held unit");
        txn_add_claim(holder->claims[sid], slice(key), TxnClaimMode::Write);
        Shard::WatchReservation claim{holder, &holder->decision.epoch, &holder->decision.aborted,
            &holder->watch_refs, &holder_client, 0, false, true}; claim.unit_kind = 1;
        require(shard.watch_place_unit(holder->claims[sid], claim), "place held unit");
        holder->decision.phase.store(TxnPhase::Executing); holder->execution_noted[sid] |= 8;
        Client watcher{-1}; f.client(watcher); watcher.set_id(8301);
        Request request({"WATCH", key}); MultiExecState* watch = nullptr;
        require(multi_handle_io(f.server, watcher, request.op, f.io_id, watch) == MultiIoAction::Dispatch,
                "actual WATCH fragment");
        Op* carrier = watcher.rob().acquire(); require(carrier, "WATCH carrier");
        carrier->spec = request.op.spec; carrier->attach_multi_state(watch); watcher.rob().publish();
        multi_dispatch_started(watcher, watch);
        // Restrict the fixture to its real physical alias on this shard. Other
        // aliases are dispatched below and cannot hide this refusal.
        for (int32_t target : watch->shards) {
            auto& owner = f.loops[f.server.worker_of_shard(target)];
            require(owner.execute(multi_make_task(&watcher, 0, target, watch)), "WATCH arrival");
        }
        require(loop.multi_retries_.markless_count > 0 && (shard.txn_boundary_notes() & Shard::TxnWatchNote),
                "H3 WATCH refusal is non-vacuous and leaves a shard note");
        require(!loop.template service_txn_boundary<false>(), "refused markless waiter closes chain");
        holder->decision.epoch.store(f.server.atomic_commit());
        shard.watch_finish_unit(holder->claims[sid], holder);
        require(loop.template service_txn_boundary<false>(), "boundary services WATCH before another unit");
        // The other physical aliases may still be waiting on their all-owner
        // barrier. They are ordinary runnable work; no new unit is needed.
        for (unsigned round = 0; round < 64 && watch->tasks_pending.load(); ++round)
            for (uint32_t tid = 0; tid < f.server.nthreads(); ++tid)
                f.loops[tid].template service_multi_retries<false>();
        require(!watch->tasks_pending.load() && !watcher.watch_dirty(), "WATCH completes cleanly at boundary");
        shard.watch_write_committed(slice(key));
        require(watcher.watch_dirty(), "later writer observes boundary registration");
        for (const auto& watched : watch->watched)
            f.server.shard(watched.shard).watch_remove(
                Slice(watched.key.data(), watched.key.size(), watched.ns), &watcher, watch->watch_generation);
        carrier->detach_scatter_state(); release_records(f.server);
        destroy_multi_state(watch); destroy_multi_state(holder);
        std::puts("PASS H3 WATCH boundary and subsequent invalidation");
    }
};
}
int main(int argc, char** argv) {
    require(argc == 3, "local|boundary 1s|2s");
    require(command_registry_init(false), "commands");
    const bool fused = std::string(argv[2]) == "1s";
    if (std::string(argv[1]) == "local") {
        if (fused) TxnChainTest::local_unit<true>(); else TxnChainTest::local_unit<false>();
    } else {
        if (fused) TxnChainTest::watch_boundary<true>(); else TxnChainTest::watch_boundary<false>();
    }
}
