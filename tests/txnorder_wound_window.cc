// AT4-WOUND-1: deterministic production owner turns, no timing assumptions.
#include <functional>
#include <tuple>
void woundfix_pause(int site, const void* unit);
#define main survivors_fixture_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace {
void group_window(Server& server, const Config& cfg, bool oom, bool wounded_oom = false) {
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

    if (wounded_oom) {
        TxnPhase placing = TxnPhase::Placing;
        require(state.group_attempt()->phase.compare_exchange_strong(placing, TxnPhase::Wounded),
                "wound phase precedes independent placement OOM");
    }
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
    if (oom && !wounded_oom) {
        Client receiver{-1};
        assemble_final(receiver, request.op, state, nullptr, nullptr, nullptr);
        require(request.reply() == "-ERR out of memory\r\n", "OOM wire reply, never an unmaterialized image");
        require(state.group_attempt()->phase.load() == TxnPhase::Executing,
                "terminal error closes placement against a delayed wound");
    }
    const bool valid = wounded_oom
        ? read == TxnGroupRead::Done && aborted && source_present && !accepted &&
          state.epoch.load() == kAtomicCancelledEpoch
        : oom
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
    std::puts(wounded_oom ? "PASS: wounded placement OOM cannot accept a ticket"
              : oom ? "PASS: placement allocation failure reports OOM"
                  : "PASS: wounded group cannot escape through a terminal commit");
}

void exec_window(Server& server, bool oom = false) {
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
    if (oom) {
        Shard::WatchReservation claim{state, &state->decision.epoch, &state->decision.aborted,
            &state->watch_refs, &client, 0, false, true}; claim.unit_kind = 1;
        allocation_failed = false; fail_new_after = 0;
        require(server.shard(0).watch_place_unit(state->claims[0], claim), "EXEC OOM completes placement");
        fail_new_after = -1;
        require(allocation_failed && state->decision.aborted.load(), "EXEC allocation failure inside wound gap");
    }
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

// Copy-only hooks invoke another owner's turn while the publisher is suspended.
// No hook is compiled into a release object (tools/woundfix_windows.py).
namespace {
std::function<void(int, const void*)> window_turn;
}
void woundfix_pause(int site, const void* unit) {
    if (window_turn) window_turn(site, unit);
}
namespace {
void d2_group(Server& server, bool blind, int pause) {
    const auto a = key_on(server, 1, "d2-source-"), b = key_on(server, 0, "d2-dest-");
    require(local(server, {"SET", a, "before"}) == "+OK\r\n", "group source seeded");
    require(local(server, {"DEL", b}) == ":0\r\n", "group destination absent");
    ScatterRun run(server, {"RENAMENX", a, b}, false);
    auto& state = *run.state;
    auto* attempt = state.group_attempt(); require(attempt, "bare group has version");
    auto* carrier = run.client.rob().acquire(); require(carrier, "retry carrier");
    for (const auto& arg : run.request.args) require(carrier->push_arg(slice(arg)), "retry args");
    carrier->spec = run.request.op.spec; carrier->attach_scatter_state(run.state);
    const auto age = std::tuple(attempt->age_ns, attempt->age_io, attempt->age_seq);
    require(!txn_group_arrive(state, server.shard(0), run.request.op), "first group arrival");
    require(txn_group_arrive(state, server.shard(1), run.request.op), "all group arrivals");
    Ring ring;
    auto owner = [&](int sid) {
        Task task{&run.client, 0, sid, &state};
        require(xshard_execute(task, server.shard(sid), run.request.op,
                    server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                "bounded group owner fragment completes");
        return xshard_complete(server, server.thread(server.worker_of_shard(sid)), ring, task, run.request.op);
    };
    std::unique_ptr<ScatterRun> crossing;
    if (blind) {
        const auto c = key_on(server, 2, "d2-blind-");
        crossing = std::make_unique<ScatterRun>(server, std::vector<std::string>{"MSET", b, "blind", c, "blind"});
        require(xshard_execute(Task{&crossing->client, 0, 0, crossing->state}, server.shard(0),
            crossing->request.op, server.worker_of_shard(0)) == ScatterTaskResult::Complete,
            "blind candidate installs between arrival and placement");
        require(txn_blind_scan(server.shard(0), attempt->claims[0], &state) == TxnBlind::Crossing,
                "real crossing is held open");
    } else {
        require(owner(1) == ScatterFinish::Waiting && state.images[0].present,
                "source read materialized before wound; destination outstanding");
    }
    const auto cause = blind ? TxnCounter::BlindRestarts : TxnCounter::GroupWounds;
    const auto before = server.txn_counter(cause);
    unsigned hits = 0;
    window_turn = [&](int site, const void* unit) {
        if (site != pause || unit != &state) return;
        ++hits;
        require(attempt->phase.load() == TxnPhase::Wounded && !state.aborted.load() &&
                state.epoch.load() == (pause <= 3 ? 0 : kAtomicCancelledEpoch),
                "actual group publication gap open");
        if (blind && pause == 5) {
            // Cancellation is visible, but the publisher still owes aborted.
            // This non-last placer must wait, then finish after publication.
            require(xshard_execute(Task{&run.client, 0, 1, &state}, server.shard(1), run.request.op,
                    server.worker_of_shard(1)) != ScatterTaskResult::Complete && state.pending.load() == 2,
                    "epoch-before-aborted gap cannot complete an unpublished abort");
        } else require(owner(blind ? 1 : 0) == ScatterFinish::Waiting,
                       "victim completion waits or enqueues its restart");
        require(state.phase == 1, "wound can discard reads only; no apply wave");
        if (!blind) {
            require(state.epoch.load() == kAtomicCancelledEpoch &&
                    server.multi_retry_lane(0).head.load() == &attempt->retry,
                    "group completed cancellation and enqueued restart inside gap");
            require(!txn_group_decide(state, server.atomic_commit()), "wounded group cannot accept ticket");
        }
    };
    if (blind) {
        require(!txn_group_ready(state, server.shard(0), run.request.op), "crossing cancels placement");
    } else {
        Client older_client{-1}; older_client.set_id(813);
        auto* older = fixture_allocate_state(server, older_client, 0, MultiStateKind::Execute);
        require(older, "older unit allocated");
        older->decision.age_ns = attempt->age_ns - 1;
        txn_add_claim(older->claims[1], slice(a), TxnClaimMode::Write);
        Shard::WatchReservation claim{older, &older->decision.epoch, &older->decision.aborted,
            &older->watch_refs, &older_client, 0, false, true}; claim.unit_kind = 1;
        require(server.shard(1).watch_place_unit(older->claims[1], claim), "strictly older unit wounds");
        older->decision.aborted.store(true);
        server.shard(1).watch_finish_unit(older->claims[1], older);
        destroy_multi_state(older);
    }
    window_turn = {};
    require(hits == 1 && server.txn_counter(cause) == before + 1,
            "exactly one successful phase wound counted, even when helper won epoch CAS");
    if (blind) {
        require(attempt->retry_after_ns > 0, "blind restart retains backoff");
        require(owner(0) == ScatterFinish::Waiting, "blind publisher completes aborted");
        if (pause == 5) require(owner(1) == ScatterFinish::Waiting, "waiting reader now enqueues restart");
        crossing.reset(); // discard only this fixture's unpublished blind candidate
    }
    require(local(server, {"GET", a}) == "$6\r\nbefore\r\n" && local(server, {"GET", b}) == "$-1\r\n",
            "cancelled group wrote nothing and kept source");
    require(server.multi_retry_lane(0).head.exchange(nullptr) == &attempt->retry,
            "one group retry is pending");
    attempt->retry_after_ns = 0; // advance the IO scheduler, not the version
    // Keep the old owner pins until after redispatch: retirement must not be
    // required for replay. Its lazy pins protect the old source image.
    if (server.thread_mode() == ThreadMode::Fused)
        txn_group_redispatch<true>(server, server.thread(0), ring, run.pool, state);
    else txn_group_redispatch<false>(server, server.thread(0), ring, run.pool, state);
    run.state = carrier->scatter_state();
    require(run.state && run.state != &state && run.state->group_attempt()->attempt == 1,
            "real group redispatch prepared a fresh attempt");
    auto* next = run.state->group_attempt();
    require(std::tuple(next->age_ns, next->age_io, next->age_seq) == age,
            "group restart retains the complete original version");
    unsigned tasks = 0;
    auto drain = [&](const Task& task) {
        require(task.scatter == run.state, "only redispatched group is queued"); ++tasks;
    };
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid) {
        if (server.thread_mode() == ThreadMode::Fused) server.thread(tid).drain_tasks<true>(drain);
        else server.thread(tid).drain_tasks(drain);
    }
    require(tasks == run.state->nsub, "every fresh owner fragment was actually dispatched");
    carrier->detach_scatter_state();
    std::printf("PASS: D2 group %s seam=%d: read-only discard, retry version retained, count=1\n",
                blind ? "blind" : "foreign", pause);
}

void d2_exec(Server& server, bool blind, int pause) {
    Client client{-1}; client.set_id(814);
    const auto a = key_on(server, 0, "d2-exec-a"), b = key_on(server, 1, "d2-exec-b");
    require(local(server, {"SET", a, "before"}) == "+OK\r\n", "EXEC source seeded");
    require(multi_io(server, client, {"MULTI"}) == "+OK\r\n", "MULTI");
    require(multi_io(server, client, {"SET", a, "after"}) == "+QUEUED\r\n", "queued write");
    require(multi_io(server, client, {"GET", b}) == "+QUEUED\r\n", "queued remote read");
    Request request({"EXEC"}); MultiExecState* state = nullptr;
    require(multi_handle_io(server, client, request.op, 0, state) == MultiIoAction::Dispatch && state,
            "two-owner EXEC prepared");
    initialize_multi_owner_record_refs(*state); multi_dispatch_started(client, state);
    auto* carrier = client.rob().acquire(); require(carrier, "EXEC carrier"); carrier->spec = request.op.spec;
    require(!execute_watch_phase(*state, server.shard(0)), "EXEC first arrival waits");
    require(execute_watch_phase(*state, server.shard(1)), "one placement leaves last owner held");
    std::unique_ptr<ScatterRun> crossing;
    if (blind) {
        crossing = std::make_unique<ScatterRun>(server, std::vector<std::string>{"MSET", a, "blind", b, "blind"});
        require(xshard_execute(Task{&crossing->client, 0, 0, crossing->state}, server.shard(0),
            crossing->request.op, server.worker_of_shard(0)) == ScatterTaskResult::Complete,
            "EXEC crossing installs after arrival");
    }
    bool done[16]{}; bool terminal = false;
    auto finish = [&] {
        for (unsigned round = 0; round < 64 && state->tasks_pending.load(); ++round)
            for (int sid : state->shards) if (!done[sid]) {
                const auto result = multi_execute_task(server, multi_make_task(&client, 0, sid, state),
                    server.shard(sid), server.worker_of_shard(sid), 0, nullptr);
                terminal |= result == MultiTaskResult::Final;
                done[sid] = !multi_task_retry(result);
            }
        require(!state->tasks_pending.load() && state->finalized.load(), "all EXEC owners joined finalizer");
        require(!terminal && state->doomed && state->decision.epoch.load() == kAtomicCancelledEpoch &&
            server.multi_retry_lane(0).head.load() == &state->retry, "EXEC finalizer enqueues restart");
    };
    const auto cause = blind ? TxnCounter::BlindRestarts : TxnCounter::Wounds;
    const auto before = server.txn_counter(cause); unsigned hits = 0;
    window_turn = [&](int site, const void* unit) {
        if (site != pause || unit != state) return;
        ++hits;
        require(state->decision.phase.load() == TxnPhase::Wounded && !state->decision.aborted.load() &&
            state->decision.epoch.load() == (pause <= 3 ? 0 : kAtomicCancelledEpoch), "EXEC gap opened");
        if (blind) {
            require(multi_task_retry(multi_execute_task(server, multi_make_task(&client, 0, 1, state),
                server.shard(1), server.worker_of_shard(1), 0, nullptr)), "other EXEC owner waits for publisher join");
            require(!state->watch_phase_done.load(), "no EXEC command can start inside blind gap");
        } else {
            require(execute_watch_phase(*state, server.shard(0)), "last placement helps wound");
            finish();
        }
    };
    if (blind) require(execute_watch_phase(*state, server.shard(0)), "blind placement ends aborted");
    else {
        Client older_client{-1}; older_client.set_id(815);
        auto* older = fixture_allocate_state(server, older_client, 0, MultiStateKind::Execute);
        require(older, "older EXEC allocated"); older->decision.age_ns = state->decision.age_ns - 1;
        txn_add_claim(older->claims[1], slice(b), TxnClaimMode::Write);
        Shard::WatchReservation claim{older, &older->decision.epoch, &older->decision.aborted,
            &older->watch_refs, &older_client, 0, false, true}; claim.unit_kind = 1;
        require(server.shard(1).watch_place_unit(older->claims[1], claim), "older wounds EXEC");
        older->decision.aborted.store(true); server.shard(1).watch_finish_unit(older->claims[1], older);
        destroy_multi_state(older);
    }
    window_turn = {};
    require(hits == 1 && server.txn_counter(cause) == before + 1, "one successful EXEC phase wound counted");
    if (blind) { finish(); require(state->backoff.load() && state->retry_after_ns, "blind EXEC backoff"); crossing.reset(); }
    require(local(server, {"GET", a}) == "$6\r\nbefore\r\n", "wounded EXEC executed no writes");
    for (int sid : state->shards) require(!(state->execution_noted[sid] & 8), "no EXEC owner crossed start bit");
    auto* next = multi_rebuild_attempt(*state);
    require(next && next->attempt == state->attempt + 1 &&
        std::tuple(next->decision.age_ns, next->decision.age_io, next->decision.age_seq) ==
        std::tuple(state->decision.age_ns, state->decision.age_io, state->decision.age_seq), "EXEC original version retained");
    destroy_multi_state(next); server.multi_retry_lane(0).head.store(nullptr);
    release_records(server); destroy_multi_state(state);
    std::printf("PASS: D2 EXEC %s seam=%d: no execution, retry version retained, count=1\n", blind ? "blind" : "foreign", pause);
}
}
namespace {
void d2_rank(Server& server) {
    struct Unit {
        Server& server; Client client{-1}; MultiExecState* exec;
        ScatterState group; TxnGroupAttempt attempt; bool grouped;
        Unit(Server& s, bool g) : server(s), exec(fixture_allocate_state(s, client, 0, MultiStateKind::Execute)), grouped(g) {
            require(exec, "rank unit allocated"); group.server = &server;
            group.group_attempt_storage = &attempt; group.watch_refs.store(ScatterState::kGroupAttemptRef);
            attempt.arrived.resize(server.nshards());
            attempt.place_blockers = std::make_unique<TxnPlaceBlocker[]>(server.nshards());
        }
        auto& phase() { return grouped ? attempt.phase : exec->decision.phase; }
        auto& epoch() { return grouped ? group.epoch : exec->decision.epoch; }
        auto& aborted() { return grouped ? group.aborted : exec->decision.aborted; }
        const void* token() { return grouped ? static_cast<void*>(&group) : exec; }
        void age(uint64_t ns, uint32_t io, uint32_t seq) {
            attempt.age_ns = exec->decision.age_ns = ns;
            attempt.age_io = exec->decision.age_io = io;
            attempt.age_seq = exec->decision.age_seq = seq;
        }
        bool place(const std::string& key) {
            if (exec->claims[0].empty()) txn_add_claim(exec->claims[0], slice(key), TxnClaimMode::Write);
            Shard::WatchReservation r{token(), &epoch(), &aborted(), grouped ? &group.watch_refs : &exec->watch_refs,
                &client, 0, false, true}; r.unit_kind = grouped ? 2 : 1;
            return server.shard(0).watch_place_unit(exec->claims[0], r);
        }
        ~Unit() {
            aborted().store(true);
            server.shard(0).watch_finish_unit(exec->claims[0], token());
            destroy_multi_state(exec);
        }
    };
    const auto key = key_on(server, 0, "d2-rank-"); unsigned cells = 0;
    for (bool holder_group : {false, true}) for (bool requester_group : {false, true})
        for (bool executing : {false, true}) for (int field = 0; field < 3; ++field)
            for (int order : {-1, 0, 1}) {
                Unit holder(server, holder_group), requester(server, requester_group);
                holder.age(100, 10, 10);
                requester.age(field == 0 ? 100 + order : 100,
                              field == 1 ? 10 + order : 10, field == 2 ? 10 + order : 10);
                require(holder.place(key), "rank holder placed first");
                if (executing) holder.phase().store(TxnPhase::Executing);
                const auto cause = holder_group ? TxnCounter::GroupWounds : TxnCounter::Wounds;
                const auto before = server.txn_counter(cause);
                const bool wounded = order < 0 && !executing;
                require(requester.place(key) == wounded, "only strictly older unit can bypass placing holder");
                require(holder.aborted().load() == wounded &&
                    holder.epoch().load() == (wounded ? kAtomicCancelledEpoch : 0) &&
                    holder.phase().load() == (wounded ? TxnPhase::Wounded :
                        executing ? TxnPhase::Executing : TxnPhase::Placing),
                        "equal/younger units wait; executing holder immune at every version component");
                require(server.txn_counter(cause) == before + wounded, "successful phase wounds counted exactly");
                ++cells;
            }
    std::printf("PASS: D2 rank: %u kind/phase/lexicographic age cells\n", cells);
}
void d2_condition(Server& server, bool wounded = false) {
    const auto a = key_on(server, 0, "d2-nx-a"), b = key_on(server, 1, "d2-nx-b");
    require(local(server, {"SET", a, "before"}) == "+OK\r\n", "MSETNX veto seeded");
    ScatterRun run(server, {"MSETNX", a, "after", b, "after"}, false);
    if (wounded) {
        require(!txn_group_arrive(*run.state, server.shard(0), run.request.op), "NX first arrival");
        require(txn_group_arrive(*run.state, server.shard(1), run.request.op), "NX arrivals before veto owner turn");
        // Owner zero now places first and sees its existing key. The other
        // owner has not placed yet, so the terminal condition is still Placing.
    }
    Ring ring; bool done[16]{}; bool queued = false;
    for (unsigned turn = 0; turn < 64 && !queued; ++turn)
        for (unsigned i = 0; i < run.state->nsub; ++i) {
            int sid = run.state->groups[i].shard; if (done[sid]) continue;
            Task task{&run.client, 0, sid, run.state};
            if (xshard_execute(task, server.shard(sid), run.request.op, server.worker_of_shard(sid)) !=
                ScatterTaskResult::Complete) continue;
            done[sid] = true;
            queued |= xshard_complete(server, server.thread(server.worker_of_shard(sid)), ring, task,
                                      run.request.op) == ScatterFinish::CommitQueued;
        }
    require(queued && run.state->aborted.load() && run.state->epoch.load() == 0 &&
        run.state->final_reply == FinalReply::Integer && run.state->final_integer == 0 &&
        !server.multi_retry_lane(0).head.load(), "ordinary failed NX remains a terminal zero reply");
    if (wounded) {
        // A wounder can have passed the liveness check before the NX owner
        // published aborted. Its delayed phase CAS must still be completed.
        TxnPhase placing = TxnPhase::Placing;
        require(run.state->group_attempt()->phase.compare_exchange_strong(placing, TxnPhase::Wounded),
                "NX terminal abort still has a pending wound phase");
    }
    require(txn_group_decide(*run.state, server.atomic_commit()) != wounded,
            "non-wound abort keeps ticket; wounded NX restarts");
    if (wounded) require(run.state->epoch.load() == kAtomicCancelledEpoch, "NX wound epoch cancelled");
    require(local(server, {"GET", a}) == "$6\r\nbefore\r\n" && local(server, {"GET", b}) == "$-1\r\n",
            "failed NX writes nothing");
    std::puts(wounded ? "PASS: wounded NX condition restarts" : "PASS: non-wound MSETNX condition remains terminal");
}
void d2_windows(Server& server) {
    for (int point : {1, 4}) { d2_group(server, false, point); d2_exec(server, false, point); }
    for (int point : {2, 5}) d2_group(server, true, point);
    for (int point : {3, 6}) d2_exec(server, true, point);
    d2_rank(server); d2_condition(server);
    require(server.txn_counter(TxnCounter::OrderViolations) == 0, "D2 order violation count zero");
}
}

int main(int argc, char** argv) {
    require(argc == 3, "usage: group|exec|oom 1s|2s");
    require(command_registry_init(false), "registry initialized");
    Config cfg;
    cfg.databases = 1; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.atomic = 1; cfg.save.clear();
    cfg.thread_mode = std::string(argv[2]) == "1s"
        ? ThreadMode::Fused : ThreadMode::Split;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "serverless owners initialized");
    command_bind_server(&server);
    std::string error; require(acl_initialize(server, cfg, error), "default ACL initialized");

    const std::string name = argv[1];
    if (name == "d2" || name == "no-arm")
        for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
            require(cfg.thread_mode == ThreadMode::Fused
                ? server.thread(tid).init_task_inbox_local_fused()
                : server.thread(tid).init_task_inbox_local(server.placement().ifid_threads(),
                                                         server.placement().ex_threads()),
                    "serverless owner inbox allocated for real retry dispatch");
    if (name == "group" || name == "oom") group_window(server, cfg, name == "oom");
    else if (name == "exec") exec_window(server);
    else if (name == "d2") d2_windows(server);
    else if (name == "abort-gap") {
        group_window(server, cfg, true, true);
        exec_window(server, true);
        d2_condition(server, true);
    }
    else if (name == "no-arm") d2_group(server, false, 0);
    else require(false, "known wound-window case");
}
