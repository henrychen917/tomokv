// AT4.12 owner turns, using production placement, writer gates and rule P.
// No listener, worker, wall-clock delay or model of the queue is used.
#define main survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace {
struct ScriptUnit {
    Server& server;
    Client client{-1};
    std::unique_ptr<MultiExecState> exec;
    ScatterState state;
    TxnGroupAttempt attempt;
    bool script;
    ScriptUnit(Server& s, bool e, uint64_t age) : server(s), script(e) {
        client.set_id(e ? 801 : 802);
        exec.reset(allocate_state(s, client, 0, MultiStateKind::Execute));
        require(bool(exec), "owner unit allocation");
        exec->read_only = false;
        state.server = &s; state.kind = Kind::Script;
        state.watch_refs.store(ScatterState::kGroupAttemptRef);
        state.group_attempt_storage = &attempt;
        attempt.arrived.resize(s.nshards());
        attempt.place_blockers = std::make_unique<TxnPlaceBlocker[]>(s.nshards());
        attempt.age_ns = exec->decision.age_ns = age;
    }
    auto& phase() { return script ? attempt.phase : exec->decision.phase; }
    auto& epoch() { return script ? state.epoch : exec->decision.epoch; }
    auto& aborted() { return script ? state.aborted : exec->decision.aborted; }
    const void* token() { return script ? static_cast<void*>(&state) : exec.get(); }
    void claim(unsigned sid, const std::string& key) {
        txn_add_claim(exec->claims[sid], slice(key), TxnClaimMode::Write);
    }
    void unpin() {
        for (unsigned sid : {0, 1})
            (script ? attempt.place_blockers[sid] : exec->place_blockers[sid]).clear();
    }
    bool place(unsigned sid) {
        Shard::WatchReservation entry{token(), &epoch(), &aborted(),
            script ? &state.watch_refs : &exec->watch_refs, &client, 0, false, true};
        entry.unit_kind = script ? 2 : 1;
        return server.shard(sid).watch_place_unit(exec->claims[sid], entry);
    }
    void finish() {
        epoch().store(server.atomic_commit());
        for (unsigned sid : {0, 1}) server.shard(sid).watch_finish_unit(exec->claims[sid], token());
    }
    ~ScriptUnit() {
        aborted().store(true); unpin();
        for (unsigned sid : {0, 1}) server.shard(sid).watch_finish_unit(exec->claims[sid], token());
    }
};

void clock_cycle(Server& server, bool realtime) {
    const auto a = key_on(server, 0, "at412-age-a");
    const auto ap = key_on(server, 0, "at412-age-ap");
    const auto b = key_on(server, 1, "at412-age-b");
    ScriptUnit e(server, true, realtime ? now_realtime_ms()*1000000 : now_ns());
    e.claim(0, a); e.claim(1, b);
    require(e.place(0), "E's first owner places");
    e.attempt.arrived[0] |= 4; // a placed kind-2 fragment is already started
    Request writer({"MSET", a, "W", ap, "W"}); writer.op.mark_local_xshard();
    writer.op.hash = FlatStore::hash_key(slice(a));
    require(!multi_plain_write_ready(server.shard(0), writer.op), "W waits on E");
    const auto stamp = server.shard(0).watch_writer_stamp(slice(a), &writer.op);
    require(stamp && server.shard(0).watch_writer_stamp(slice(ap), &writer.op) == stamp,
            "W marks both keys with the observed monotonic stamp");
    ScriptUnit v(server, false, stamp+1);
    v.claim(1, b); v.claim(0, ap);
    require(v.place(1), "V places b before meeting W");
    require(!v.place(0), "V waits on W's earlier episode");
    const bool e_waits = !e.place(1);
    const bool cycle = e_waits && !v.place(0) &&
                       !multi_plain_write_ready(server.shard(0), writer.op);
    require(cycle == realtime, "H1 exists exactly with the non-monotonic age");
    if (!realtime) require(v.epoch().load() == kAtomicCancelledEpoch,
                            "compliant E wounds V and breaks the dependency");
    std::printf("H1 realtime_age=%u E->V->W->E=%u\n", realtime, cycle);
    v.aborted().store(true); e.aborted().store(true); v.unpin(); e.unpin();
    for (unsigned sid : {0, 1}) {
        server.shard(sid).watch_finish_unit(v.exec->claims[sid], v.token());
        server.shard(sid).watch_finish_unit(e.exec->claims[sid], e.token());
    }
    require(multi_plain_write_ready(server.shard(0), writer.op), "all writer marks drain");
}

void ticket_cycle(Server& server, bool held) {
    const auto x = key_on(server, 0, "at412-ticket-x");
    const auto y = key_on(server, 1, "at412-ticket-y");
    auto& shard = server.shard(0);
    const auto hash = FlatStore::hash_key(slice(x));
    require(local(server, {"SET", x, "old"}) == "+OK\r\n", "initial version");
    require(shard.store().atomic_script_pin(hash, slice(x)), "writer produces a real MVCC record");
    if (held) server.atomic_commit_reserve(); // deliberately non-compliant E
    require(local(server, {"SET", x, "new"}) == "+OK\r\n", "W publishes after E's bracket");
    ScriptUnit u(server, false, now_ns()), e(server, true, now_ns());
    u.claim(1, y); e.claim(1, y);
    require(u.place(1), "U holds the claim needed by E");
    u.phase().store(TxnPhase::Executing); u.exec->execution_noted[1] |= 8;
    const bool u_waits = !multi_touch_key(*u.exec, shard, hash, slice(x), false);
    const bool e_waits = !e.place(1);
    require(e_waits && u_waits == held, "H3 exists exactly when E holds a bracket while placing");
    std::printf("H3 early_bracket=%u E->U->E=%u\n", held, e_waits && u_waits);
    if (held) server.atomic_commit_publish();
    require(multi_touch_key(*u.exec, shard, hash, slice(x), false), "decision-time bracket removes rule-P edge");
    u.finish(); e.unpin(); require(e.place(1), "E places after U's decision"); e.finish();
    shard.store().atomic_script_unpin(hash, slice(x));
    release_records(server);
}

uint64_t queue_visits(Server& server, unsigned n) {
    const auto key = key_on(server, 0, "at412-queue");
    std::vector<std::unique_ptr<ScriptUnit>> units;
    for (unsigned i = 0; i <= n; ++i) {
        units.push_back(std::make_unique<ScriptUnit>(server, true, i+1));
        auto& u = *units.back(); u.claim(0, key);
        require(u.place(0) == (i == 0), "one holder and n real script waiters");
        if (!i) { u.phase().store(TxnPhase::Executing); u.attempt.arrived[0] |= 4; }
    }
    auto& tail = *units.back();
    require(tail.exec->claims[0][0].waiter.queue->waiters == n, "simultaneous waiter witness");
    tail.unpin(); registry_visits.store(0);
    require(!tail.place(0), "uncached production placement still waits");
    const auto visits = registry_visits.load();
    for (auto& u : units) { u->aborted().store(true); u->unpin(); }
    for (auto& u : units) server.shard(0).watch_finish_unit(u->exec->claims[0], u->token());
    for (auto& u : units) require(u->state.watch_refs.load() == ScatterState::kGroupAttemptRef,
                                  "queue and blocker lifetime pins drain");
    std::printf("script placement waiters=%u registry_visits=%llu\n", n, (unsigned long long)visits);
    return visits;
}

void wound_window(Server& server) {
    ScatterState state; state.server = &server; state.kind = Kind::Script;
    require(script_group_prepare(state, server, 0), "script sidecar exists before owner wave");
    state.group_attempt()->phase.store(TxnPhase::Wounded);
    require(!state.epoch.load() && !state.aborted.load(), "pause wound before cancellation publication");
    Request op({"EVAL", "return 1", "0"}); Client client{-1};
    require(script_group_read(Task{&client,0,0,&state}, server.shard(0), op.op) == ScatterTaskResult::Complete,
            "wounded script stops materialization");
    require(state.aborted.load() && state.epoch.load() == kAtomicCancelledEpoch,
            "script guard publishes cancellation before completion");
    uint64_t zero = 0;
    require(!state.epoch.compare_exchange_strong(zero, 123), "terminal commit cannot win the wound window");
    require(txn_group_release(state), "empty sidecar retires");
    std::puts("AT4-WOUND-1 script guard PASS; generic wound path unchanged");
}

void final_window(Server& server, bool omit_owner_close) {
    ScatterState state; state.server = &server; state.kind = Kind::Script;
    state.script_phase = ScriptPhase::Unpin; state.pending.store(1);
    Client client{-1}; Request op({"EVAL", "return 1", "0"}); Ring ring;
    auto& owner = server.thread(server.worker_of_shard(0));
    Task task{&client,0,0,&state};
    const auto before = server.atomic_apply_inflight();
    server.atomic_apply_open(0, state.apply_open);
    const auto result = omit_owner_close
        ? xshard_complete_script<false>(server, owner, ring, task, op.op, state)
        : xshard_complete_impl<false>(server, owner, ring, task, op.op);
    require(result == ScatterFinish::Final, "real final UNPIN completion");
    require(server.atomic_apply_inflight() == before + unsigned(omit_owner_close),
            "S1 falsifier observes window still open before IO retirement");
    server.atomic_apply_close(owner.id(), state.apply_open);
    std::printf("S1 omitted_owner_close=%u SAVE_would_wait=%u\n", omit_owner_close, omit_owner_close);
}

void lane_close(Server& server) {
    auto& lane = server.multi_retry_lane(0);
    require(!lane.script_admission && !lane.script_window, "idle FIFO allocates nothing");
    std::array<ScatterState,4> slots;
    for (auto& state : slots) {
        state.server = &server; state.owner_io = 0;
        script_window_admit(state, nullptr);
    }
    Client first{-1}, second{-1}; first.set_id(801); second.set_id(802);
    require(!script_window_wait(server,0,first) && !script_window_wait(server,0,second),
            "full window queues in arrival order");
    script_window_release(slots[0]); script_window_refresh(server,0);
    require(script_window_wait(server,0,first) && !script_window_wait(server,0,second),
            "later waiter cannot overtake a free slot");
    first.mark_closing(); script_window_forget(server,0,first);
    require(script_window_wait(server,0,second), "closing head releases its FIFO membership");
    script_window_forget(server,0,second); // same operation at migration
    for (auto& state : slots) script_window_release(state);
    script_window_refresh(server,0);
    require(!lane.script_admission && !lane.script_releases.load() && lane.script_window->fifo.empty(),
            "EX release plus IO retirement is idempotent and slots settle to zero");
    lane.script_window.reset();

    Client closing{-1}; auto* op = closing.rob().acquire(); require(op, "lane carrier");
    closing.rob().publish(); closing.mark_closing();
    ScatterState previous; previous.server = &server;
    require(script_group_prepare(previous,server,0), "retired optimistic sidecar");
    previous.commit_client = &closing; previous.commit_op_id = 0;
    previous.epoch.store(kAtomicCancelledEpoch); previous.aborted.store(true);
    ScatterArenaPool pool; Ring ring;
    script_escalate_redispatch<false>(server,server.thread(0),ring,pool,previous);
    require(op->state.load() == OpState::Done && !previous.apply_open.load() &&
            !previous.admitted && !previous.snapshot_registered,
            "closed lane command drops without a new wave, window, credit or cut");
    require(txn_group_release(previous), "closed lane sidecar retires");
    ScatterState oom; oom.server=&server;
    allocation_failed=false; fail_new_after=0;
    require(!script_group_prepare(oom,server,0) && allocation_failed && !oom.group_attempt(),
            "sidecar OOM is final and leaves no partial ownership");
    std::puts("FIFO close/migration, lane disconnect, sidecar OOM and slot settle PASS");
}
}

int main(int argc, char** argv) {
    static_assert(sizeof(ScatterState) == 896, "AT4.12 uses existing padding only");
    require(command_registry_init(false), "command registry");
    Config cfg; cfg.databases=1; cfg.shards=16; cfg.even_ifid=6; cfg.even_ex=2;
    cfg.key_lb=cfg.client_lb=cfg.flip_auto=0; cfg.save.clear();
    cfg.thread_mode=argc>1 && std::string(argv[1])=="1s" ? ThreadMode::Fused : ThreadMode::Split;
    cfg.atomic=argc>2 ? std::atoi(argv[2]) : 1;
    cfg.net_io=argc>3 && std::string(argv[3])=="epoll" ? NetIoEngine::Epoll : NetIoEngine::Uring;
    Server server; require(server.prepare_boot(cfg)&&server.init(cfg), "serverless owners");
    command_bind_server(&server);
    for (bool bad : {true, false}) { clock_cycle(server,bad); ticket_cycle(server,bad); final_window(server,bad); }
    wound_window(server);
    lane_close(server);
    const auto a = queue_visits(server,16), b = queue_visits(server,128);
    require(a && b*10 <= a*12, "128/16 waiter placement visits <= 1.2");
    release_records(server);
    std::puts("AT4.12 owner turns PASS");
}
