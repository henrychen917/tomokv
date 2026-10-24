// Directed regressions for SURVIVING.md's atomic/transaction/script lane.
// Includes the real owner implementation so phases and allocation failures can be interleaved
// deterministically. No worker is started, no socket is opened, and no clock race is required.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#define TOMO_STORE_REGRESSION_TEST
#include "src/cmd/xshard.cc"
#include "src/core/read_local.h"
#include <cstdio>
#include <type_traits>

namespace {
thread_local int fail_new_after = -1;
thread_local bool allocation_failed = false;
}
__attribute__((noinline)) void* operator new(std::size_t size) {
    if (fail_new_after >= 0 && fail_new_after-- == 0) {
        fail_new_after = -1;
        allocation_failed = true;
        throw std::bad_alloc();
    }
    if (void* p = std::malloc(size ? size : 1)) return p;
    throw std::bad_alloc();
}
__attribute__((noinline)) void operator delete(void* p) noexcept { std::free(p); }
__attribute__((noinline)) void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void* operator new[](std::size_t size) { return ::operator new(size); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }
// Keep nothrow allocations in the same malloc/free domain as this fixture's
// throwing allocator. ASAN otherwise supplies nothrow new while our delete
// frees its result, reporting an allocator mismatch in read-local teardown.
void* operator new(std::size_t size, const std::nothrow_t&) noexcept {
    try { return ::operator new(size); } catch (const std::bad_alloc&) { return nullptr; }
}
void* operator new[](std::size_t size, const std::nothrow_t&) noexcept {
    return ::operator new(size, std::nothrow);
}
void operator delete(void* p, const std::nothrow_t&) noexcept { std::free(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { std::free(p); }

namespace tomo {
struct AtomicSurvivorsTest {
    static void publish_stale_sample(Server& server, uint64_t drawn) {
        // Exactly the last half of A's publication, after B reserved and
        // published between A's sequence load and A's decrement.
        if (server.atomic_commit_inflight_.fetch_sub(1, std::memory_order_acq_rel) != 1)
            std::abort();
        uint64_t safe = server.atomic_commit_safe_.load(std::memory_order_relaxed);
        while (safe < drawn && !server.atomic_commit_safe_.compare_exchange_weak(
                   safe, drawn, std::memory_order_release, std::memory_order_relaxed)) {}
    }
};
}

using namespace tomo;
namespace {
void require(bool yes, const char* why) {
    if (!yes) { std::fprintf(stderr, "FAIL: %s\n", why); std::exit(1); }
}
Slice slice(const std::string& s) { return Slice(s.data(), s.size()); }
struct Request {
    std::vector<std::string> args;
    Op op;
    explicit Request(std::vector<std::string> a) : args(std::move(a)) {
        op.reset();
        for (const auto& s : args) require(op.push_arg(slice(s)), "argument allocation");
        op.spec = command_lookup(op.arg(0));
        require(op.spec != nullptr, "registered command");
    }
    std::string reply() const { return std::string(op.reply.data(), op.reply.size()); }
};
int sid(Server& server, const std::string& key) {
    return server.router().shard_of(FlatStore::hash_key(slice(key)));
}
std::string key_on(Server& server, int target, const char* prefix) {
    for (unsigned i = 0; i < 100000; i++) {
        std::string key = std::string(prefix) + std::to_string(i);
        if (sid(server, key) == target) return key;
    }
    require(false, "find a key on the required shard");
    return {};
}
std::string local(Server& server, std::vector<std::string> args, uint64_t conn = 91,
                  bool local_multi = false) {
    Request r(std::move(args));
    const int shard_id = r.args.size() > 1 ? sid(server, r.args[1]) : 0;
    Shard& shard = server.shard(shard_id);
    shard.set_cached_now_ms(now_realtime_ms(), 0);
    r.op.shard = shard_id;
    r.op.hash = r.args.size() > 1 ? FlatStore::hash_key(r.op.arg(1)) : 0;
    if (local_multi) r.op.mark_local_xshard();
    PlainForeignReadScope scope;
    require(xshard_plain_prepare(server, shard, r.op, conn, scope), "plain preparation");
#if __has_include("src/cmd/watch_modified.h")
    if (shard.has_watches()) watch_execute_handler(shard, r.op);
    else r.op.spec->handler(shard, r.op);
#else
    r.op.spec->handler(shard, r.op);
#endif
    xshard_plain_finish(shard, scope);
#if !__has_include("src/cmd/watch_modified.h")
    if (r.op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))
        multi_plain_write_committed(shard, r.op);
#endif
    return r.reply();
}
void release_records(Server& server) {
    for (unsigned s = 0; s < server.nshards(); s++)
        server.shard(s).store().atomic_shutdown_release_records();
}
std::string multi_io(Server& server, Client& client, std::vector<std::string> args) {
    Request r(std::move(args));
    MultiExecState* state = nullptr;
    const auto action = multi_handle_io(server, client, r.op, 0, state);
    if (action == MultiIoAction::LocalDone) return r.reply();
    require(action == MultiIoAction::Dispatch && state, "MULTI owner dispatch");
    state->now_cut_ms = now_realtime_ms();
    for (auto& command : state->commands)
        if (command->scatter) command->scatter->now_cut_ms = state->now_cut_ms;
    initialize_multi_owner_record_refs(*state);
    multi_dispatch_started(client, state);
    auto* carrier = client.rob().acquire();
    require(carrier != nullptr, "public transaction carrier allocated");
    carrier->spec = r.op.spec;
    std::vector<bool> done(state->shards.size(), false);
    unsigned remaining = done.size();
    for (unsigned pass = 0; remaining && pass < 1000; pass++) {
        for (unsigned i = 0; i < done.size(); i++) {
            if (done[i]) continue;
            const int s = state->shards[i];
            const auto result = multi_execute_task(server, multi_make_task(&client, 0, s, state),
                server.shard(s), server.worker_of_shard(s), 0, nullptr);
            if (result != MultiTaskResult::Retry) { done[i] = true; remaining--; }
        }
    }
    require(!remaining, "transaction owner phases completed (no reservation cycle)");
    set_state_reply(*state, r.op);
    if (state->reset_watch) { client.next_watch_generation(); client.clear_watch_dirty(); }
    release_records(server);
    destroy_multi_state(state);
    return r.reply();
}

struct ScatterRun {
    Server& server;
    Client client{-1};
    Request request;
    ScatterArenaPool pool;
    ScatterState* state = nullptr;
    ScatterRun(Server& s, std::vector<std::string> args, bool force = true)
        : server(s), request(std::move(args)) {
        client.set_id(777);
        ScatterDispatch dispatch;
        require(xshard_prepare(server, request.op, pool, 0, client.id(), dispatch, force) ==
                ScatterPrepare::Ready, "cross-owner scatter prepared");
        state = dispatch.state;
        state->now_cut_ms = now_realtime_ms();
        require(state->nsub > 1, "scatter spans multiple shards");
    }
    void phase(ScriptPhase p) {
        state->script_phase = p;
        state->phase = p == ScriptPhase::Apply ? 2 : 1;
        if (p == ScriptPhase::Run) {
            const int s = state->script_coordinator_shard;
            require(xshard_execute(Task{&client, 0, s, state}, server.shard(s), request.op,
                    server.worker_of_shard(s)) == ScatterTaskResult::Complete, "script RUN");
            return;
        }
        const auto count = script_select_positions(*state, p);
        reset_groups(*state);
        build_groups(*state, state->hop2, count);
        if (p == ScriptPhase::Apply) initialize_owner_completion(*state);
        for (unsigned i = 0; i < state->nsub; i++) {
            const int s = state->groups[i].shard;
            require(xshard_execute(Task{&client, 0, s, state}, server.shard(s), request.op,
                    server.worker_of_shard(s)) == ScatterTaskResult::Complete, "script owner phase");
        }
    }
    ~ScatterRun() {
        if (!state->epoch.load()) state->aborted.store(true);
        for (unsigned i = 0; i < state->owner_slots; i++)
            while (state->owner_record_refs[i].remaining)
                complete_owner_record_wave(*state, i);
        release_records(server);
        xshard_destroy(state, pool, 0);
        pool.reap_deferred();
    }
};

void admission(Server& server) {
    const auto a = key_on(server, 0, "admit-a"), b = key_on(server, 0, "admit-b");
    const auto c = key_on(server, 1, "admit-c");
    const std::string value(65536, 'x');
    ScatterRun run(server, {"MSET", a, value, b, value, c, value});
    auto& store = server.shard(0).store();
    require(store.size() == 0 && !store.read_local_enabled(), "empty unborrowed admission shard");
    const auto baseline = store.accounted_bytes();
    store.configure_maxmemory(true, baseline + 100000, MaxmemoryPolicy::AllKeysRandom, 64);
    auto* group = group_for(*run.state, 0);
    require(group && group->count == 2, "two candidates share the admission owner");
    require(xshard_execute(Task{&run.client, 0, 0, run.state}, server.shard(0), run.request.op,
            server.worker_of_shard(0)) == ScatterTaskResult::Complete, "admission owner ran");
    require(group->error == WorkError::Maxmemory && run.state->aborted.load(),
            "second admission exceeded capacity");
    require(run.state->keys[run.state->key_order[group->begin]].key_anchor != nullptr,
            "first candidate was materialized but remains unlinked");
    require(store.size() == 0 && store.atomic_pending_entries() == 0,
            "failed admission installed no evictable candidate");
    store.configure_maxmemory(false, 0, MaxmemoryPolicy::NoEviction, 5);
}
void script_keys(Server& server) {
    const auto a = key_on(server, 0, "aof-key"), arg = key_on(server, 1, "aof-arg");
    require(server.worker_of_shard(0) != server.worker_of_shard(1), "distinct AOF owners");
    for (const char* verb : {"EVAL", "EVALSHA", "FCALL"}) {
        Request r({verb, "return redis.call('SET',KEYS[1],ARGV[1])", "1", a, arg});
        MultiQueuedCommand queued;
        require(queued_copy(r.op, queued), "copy queued script");
        std::vector<uint32_t> keys;
        command_key_args(queued, keys);
        require(keys == std::vector<uint32_t>{3}, "AOF participant enumeration excludes ARGV");
    }
    Request r({"EVAL", "return 42", "0", arg});
    MultiQueuedCommand queued;
    require(queued_copy(r.op, queued), "zero-key script queued");
    std::vector<uint32_t> keys;
    command_key_args(queued, keys);
    require(keys.empty(), "zero-key script creates no phantom write participant");
}
void rename(Server& server, bool watch) {
    const auto a = key_on(server, 0, "rename-a"), b = key_on(server, 1, "rename-b");
    require(server.worker_of_shard(0) != server.worker_of_shard(1), "RENAME crosses owners");
    require(local(server, {"SET", a, "old"}) == "+OK\r\n", "seed RENAME source");
    Client client(-1); client.set_id(81);
    if (watch) require(multi_io(server, client, {"WATCH", a}) == "+OK\r\n", "WATCH registered");
    require(multi_io(server, client, {"MULTI"}) == "+OK\r\n", "MULTI opened");
    if (!watch) require(multi_io(server, client, {"SET", a, "new"}) == "+QUEUED\r\n", "SET queued");
    require(multi_io(server, client, {"RENAME", a, b}) == "+QUEUED\r\n", "RENAME queued");
    const auto reply = multi_io(server, client, {"EXEC"});
    require(reply == (watch ? "*1\r\n+OK\r\n" : "*2\r\n+OK\r\n+OK\r\n"), "EXEC reply");
    require(local(server, {"GET", a}) == "$-1\r\n", "RENAME removes source");
    require(local(server, {"GET", b}) == (watch ? "$3\r\nold\r\n" : "$3\r\nnew\r\n"),
            "RENAME consumes the transaction's own source version");
}
void write_latest(Server& server) {
    const auto key = key_on(server, 0, "increment");
    require(local(server, {"SET", key, "0"}) == "+OK\r\n", "seed counter");
    auto& store = server.shard(0).store();
    const auto hash = FlatStore::hash_key(slice(key));
    require(store.atomic_script_pin(hash, slice(key)), "counter intent pinned");
    const auto cut = server.atomic_snapshot();
    require(server.atomic_commit_reserve() > cut, "unrelated reservation drawn");
    require(local(server, {"INCR", key}, 101) == ":1\r\n", "first connection increment");
    require(server.atomic_snapshot() == cut && store.atomic_has_record(hash, slice(key)),
            "safe watermark held behind a completed write");
    require(local(server, {"INCR", key}, 102) == ":2\r\n", "second connection sees first increment");
    const auto fresh = key_on(server, 0, "increment-fresh");
    const auto fresh_hash = FlatStore::hash_key(slice(fresh));
    require(store.atomic_script_pin(fresh_hash, slice(fresh)), "fresh-key intent pinned");
    require(local(server, {"SET", fresh, "new"}, 103) == "+OK\r\n", "fresh key committed after safe cut");
    require(local(server, {"MSETNX", fresh, "wrong"}, 104, true) == ":0\r\n",
            "local multi-key conditional writer sees the newest committed key");
    store.atomic_script_unpin(fresh_hash, slice(fresh));
    store.atomic_script_unpin(hash, slice(key));
    server.atomic_commit_publish();
    release_records(server);
}
void txn_intents(Server& server) {
    {
        auto& lane = server.multi_retry_lane(0);
        MultiRetryNode first, second;
        multi_enqueue_node(server, 0, first);
        multi_bind_retry_lane(server, 0);
        require(multi_retry_signal.pending.load() && lane.head.load() == &first,
                "binding a late worker signals a previously queued startup fence");
        multi_retry_signal.pending.store(false, std::memory_order_release);
        require(lane.head.exchange(nullptr, std::memory_order_acq_rel) == &first,
                "first retry drained after resetting the signal");
        multi_enqueue_node(server, 0, second);
        require(multi_retry_signal.pending.load() && lane.head.exchange(nullptr) == &second,
                "a producer after the drain raises a new signal");
        multi_retry_signal.pending.store(false);
    }
    static_assert(sizeof(AtomicScriptIntent) == 32);
    static_assert(sizeof(AtomicPendingState) == 1352);
    auto& store = server.shard(0).store();
    const std::string key = key_on(server, 0, "txn-intent");
    const auto hash = FlatStore::hash_key(slice(key));
    MultiDecision first, second;
    UnitRef one{&first.epoch, &first.aborted, &first};
    UnitRef two{&second.epoch, &second.aborted, &second};
    require(!store.atomic_has_records() && !server.script_intents_active(), "idle intent state");
    require(store.atomic_unit_pin(one, hash, slice(key)) == 1, "first unit intent installed");
    require(store.atomic_unit_pin(one, hash, slice(key)) == 0, "unit key intent deduplicated");
    require(store.atomic_has_records() && store.atomic_needs_version(hash, slice(key)),
            "unit intent forces the existing versioning path");
    require(server.atomic_work_active() && !server.script_intents_active(),
            "unit activity does not arm the script PIN guard");
    require(store.atomic_script_pin(hash, slice(key)), "PIN coexists with a unit on the same key");
    require(store.atomic_script_pin(hash, slice(key)), "duplicate PIN increments only PIN refs");
    require(store.atomic_has_script_pins() && server.script_intents_active(), "PIN prefix armed");
    require(store.atomic_unit_pin(two, 0, {}, true) == 1, "wildcard inserted after PIN prefix");
    require(!store.atomic_has_script_intent(0, {}), "wildcard cannot match ordinary key predicate");
    store.atomic_script_unpin(hash, slice(key));
    require(store.atomic_has_script_pins(), "one duplicate PIN remains");
    store.atomic_script_unpin(hash, slice(key));
    require(!store.atomic_has_script_pins() && !server.script_intents_active(),
            "last PIN disarms guard even while unit intents remain");
    require(store.atomic_unit_unpin(&first) == 1 && store.atomic_has_records(),
            "exact unit removal leaves wildcard alive");
    require(store.atomic_cleanup_unit_intents() == 0, "cleanup retains undecided unit");
    second.epoch.store(kAtomicCancelledEpoch, std::memory_order_release);
    require(store.atomic_cleanup_unit_intents() == 1, "cleanup reaps decided wildcard");
    require(!store.atomic_has_records() && !server.atomic_work_active(), "activity balances to zero");
    require(store.atomic_script_pin(hash, slice(key)), "PIN prefix re-arms from empty");
    require(store.atomic_unit_pin(one, hash, slice(key)) == 1, "unit appended to PIN prefix");
    require(store.atomic_unit_unpin(&first) == 1 && server.script_intents_active(),
            "unit removal does not decrement PIN owner accounting");
    store.atomic_script_unpin(hash, slice(key));
    require(!server.script_intents_active() && !store.atomic_has_records(), "final accounting");
    {
        Client client{-1}; client.set_id(887);
        auto* state = allocate_state(server, client, 0, MultiStateKind::Execute);
        require(state != nullptr, "shutdown attempt allocated");
        state->shards.push_back(0);
        state->exec_op_id = 0;
        require(server.atomic_try_admit(0, state->admission_generation, true),
                "shutdown attempt keeps admission credit");
        state->admitted = true;
        auto* op = client.rob().acquire();
        require(op != nullptr, "shutdown carrier allocated");
        op->attach_multi_state(state);
        client.rob().publish();
        client.atomic_group_started();
        // The generic intent cleanup API is retained for Stage B anchors.
        // EXEC placement no longer registers read intents.
        UnitRef shutdown_ref{&state->decision.epoch, &state->decision.aborted, state};
        require(store.atomic_unit_pin(shutdown_ref, hash, slice(key)) == 1,
                "shutdown legacy intent armed directly");
        server.note_txn(server.worker_of_shard(0), TxnCounter::IntentsLive);
        require(server.txn_counter(TxnCounter::IntentsLive) == 1, "live shutdown intent counted");
        store.atomic_shutdown_release_records();
        require(!store.atomic_has_records() && !server.script_intents_active() &&
                server.txn_counter(TxnCounter::IntentsLive) == 0,
                "shutdown releases a live unit intent without a PIN accounting change");
        require(state->decision.aborted.load() &&
                state->decision.epoch.load() == kAtomicCancelledEpoch,
                "shutdown withdraws an undecided attempt");
        ScatterArenaPool pool;
        std::vector<MultiExecState*> deferred;
        multi_shutdown_attempt(state, pool, deferred);
        require(deferred.empty() && server.atomic_can_admit(0),
                "shutdown releases pending attempt and admission credit");
        require(!op->multi_state() && op->state.load() == OpState::Done,
                "shutdown leaves no carrier pointer to the discarded attempt");
        require(!server.atomic_work_active(), "shutdown releases the admission credit");
    }
}

void txn_group(Server& server) {
    static_assert(sizeof(ScatterState) == 896);
    static_assert(sizeof(Shard::WatchReservation) == 88);
    static_assert(offsetof(Shard::WatchReservation, dirty_databases) == 56);
    const auto a = key_on(server, 0, "txn-group-a");
    const auto b = key_on(server, 1, "txn-group-b");
    Request request({"SMOVE", a, b, "m"});
    struct Attempt {
        Server& server;
        ScatterState state;
        KeyRef keys[2];
        ShardGroup groups[2];
        uint32_t order[2]{0, 1};
        Attempt(Server& server_, Request& request) : server(server_) {
            state.server = &server;
            state.atomic_group = state.atomic_apply = true;
            state.kind = Kind::Smove;
            state.keys = keys;
            state.groups = groups;
            state.key_order = order;
            state.key_count = state.nsub = state.group_cap = 2;
            for (uint32_t i = 0; i != 2; ++i) {
                keys[i] = KeyRef{FlatStore::hash_key(request.op.arg(i + 1)), i + 1, int32_t(i)};
                groups[i].shard = i;
                groups[i].begin = i;
                groups[i].count = 1;
            }
            require(txn_group_prepare(state, server, 0), "group cold state allocated");
        }
        ~Attempt() {
            if (!state.epoch.load()) state.aborted.store(true);
            for (uint32_t i = 0; i != 2; ++i)
                xshard_cleanup_shard_at(server.shard(i), UINT64_MAX, UINT64_MAX, 256);
            require(txn_group_release(state), "group intent/reservation lifetime pins drained");
            require(state.watch_refs.load() == 0, "cold attempt ownership released");
        }
    };
    require(local(server, {"SET", a, "old"}) == "+OK\r\n", "group predecessor seeded");
    release_records(server);
    {
        Attempt run(server, request);
        auto& state = run.state;
        require(!txn_group_ready(state, server.shard(0), request.op), "group waits for all arrivals");
        require(txn_group_arrive(state, server.shard(1), request.op), "second group arrival");
        require(txn_group_ready(state, server.shard(0), request.op), "group places source");
        require(state.watch_refs.load() == ScatterState::kGroupAttemptRef + 2,
                "source claim and lazy anchor retain the attempt");
        require(!txn_group_release(state), "live owner pins prevent sidecar release");
        Client older_client{-1}; older_client.set_id(898);
        auto* older = allocate_state(server, older_client, 0, MultiStateKind::Execute);
        older->decision.age_ns = state.group_attempt()->age_ns - 1;
        txn_add_claim(older->claims[0], slice(a), TxnClaimMode::Write);
        Shard::WatchReservation claim{older, &older->decision.epoch, &older->decision.aborted,
            &older->watch_refs, &older_client, 0, false, true};
        claim.unit_kind = 1;
        require(server.shard(0).watch_place_unit(older->claims[0], claim), "older EXEC places");
        require(state.epoch.load() == kAtomicCancelledEpoch && state.aborted.load(),
                "older EXEC wounds a placing group");
        require(!txn_group_decide(state, server.atomic_commit()), "wound cannot be overwritten by commit");
        older->decision.aborted.store(true);
        server.shard(0).watch_finish_unit(older->claims[0], older);
        destroy_multi_state(older);
    }
    release_records(server);
    {
        Attempt run(server, request);
        auto& state = run.state;
        // Suspend the doomer immediately after its CAS. The batch must take
        // its existing abort arm even before that doomer stores the flag.
        state.epoch.store(kAtomicCancelledEpoch);
        require(!state.aborted.load(),
                "cancelled word precedes doomer metadata");
        require(!txn_group_decide(state, server.atomic_commit()) && state.aborted.load(),
                "failed commit CAS publishes abort before batch completion");
    }
    {
        Attempt run(server, request);
        auto& state = run.state;
        require(!txn_group_ready(state, server.shard(0), request.op), "first fragment waits for arrival");
        require(!server.shard(0).has_watches(), "no early reservation before final fragment arrives");
        require(txn_group_arrive(state, server.shard(1), request.op), "direct destination can arrive before source readiness");
        require(txn_group_ready(state, server.shard(0), request.op) &&
                txn_group_ready(state, server.shard(1), request.op), "owners place after arrival");
        require(state.watch_refs.load() == ScatterState::kGroupAttemptRef + 4, "two reservations and two lazy cleanup anchors");
        require(!server.shard(0).watch_write_ready(slice(a)) &&
                !server.shard(1).watch_write_ready(slice(b)), "started group guards both owners' writes");
        Request writer({"SET", a, "racing"});
        writer.op.hash = run.keys[0].hash;
        writer.op.shard = 0;
        Client foreign{-1}; foreign.set_id(899);
        const Task blocked{&foreign, 0, 0, nullptr};
        require(!writer.op.atomic_hazard(), "ordinary writer starts without a hazard mark");
        require(!multi_plain_write_ready(server.shard(0), writer.op) && writer.op.atomic_hazard(),
                "reservation wait marks only the blocked writer");
        require(xshard_task_should_defer(server, server.shard(0), blocked, writer.op),
                "blocked writer parks without preventing the group's next owner wave");
        require(server.shard(0).store().find(run.keys[0].hash, slice(a)) != nullptr,
                "group does not obstruct a reader");
        const uint64_t ticket = server.atomic_commit_reserve();
        require(txn_group_decide(state, ticket), "immune group commits by CAS");
        server.atomic_commit_publish();
        require(server.atomic_can_admit(0, true), "group placement never blocks admission");
        xshard_cleanup_shard_at(server.shard(0), UINT64_MAX, UINT64_MAX, 256);
        xshard_cleanup_shard_at(server.shard(1), UINT64_MAX, UINT64_MAX, 256);
        require(multi_plain_write_ready(server.shard(0), writer.op),
                "released writer passes and removes its fairness mark");
        require(state.watch_refs.load() == ScatterState::kGroupAttemptRef && !server.shard(0).has_watches() &&
                !server.shard(1).has_watches(), "read-only owner cleanup retires every reservation");
    }
    require(server.txn_counter(TxnCounter::OrderViolations) == 0 &&
            server.txn_counter(TxnCounter::IntentsLive) == 0,
            "group unit leaves no violation or live intent");
}

void txn_help(Server& server) {
    {
        const auto a = key_on(server, 0, "txn-watch-arrive-a");
        const auto b = key_on(server, 1, "txn-watch-arrive-b");
        Client client{-1}; client.set_id(890);
        auto* state = allocate_state(server, client, 0, MultiStateKind::Execute);
        require(state != nullptr, "WATCH arrival attempt allocated");
        state->shards = {0, 1};
        state->database_map = server.databases().capture();
        state->watched = {{a, FlatStore::hash_key(slice(a)), 0, 0, 0},
                          {b, FlatStore::hash_key(slice(b)), 1, 0, 0}};
        state->watch_pending.store(2);
        state->read_only = false;
        for (const auto& key : state->watched)
            require(server.shard(key.shard).watch_add(slice(key.key), &client,
                        state->watch_generation), "WATCH arrival registry armed");
        require(!execute_watch_phase(*state, server.shard(0)),
                "first fragment waits for all participants before reserving");
        require(server.shard(0).watch_write_ready(slice(a)),
                "a writer cannot hide missing EXEC fragments behind a WATCH claim");
        require(!execute_watch_phase(*state, server.shard(0)) &&
                state->watch_arrived.load() == 1, "arrival is counted once per shard");
        require(execute_watch_phase(*state, server.shard(1)) &&
                execute_watch_phase(*state, server.shard(0)),
                "all arrivals allow the existing WATCH validation barrier to finish");
        require(!server.shard(0).watch_write_ready(slice(a)) &&
                !server.shard(1).watch_write_ready(slice(b)),
                "validated WATCH claims still block ordinary writers");
        state->decision.aborted.store(true);
        finalize_reservations(*state, server.shard(0));
        finalize_reservations(*state, server.shard(1));
        require(server.shard(0).watch_write_ready(slice(a)) &&
                server.shard(1).watch_write_ready(slice(b)), "decided claims are released");
        destroy_multi_state(state);
    }
    {
        const auto key = key_on(server, 0, "txn-rule-p");
        auto& shard = server.shard(0);
        auto& store = shard.store();
        const auto first = server.atomic_commit_reserve();
        const auto last = server.atomic_commit_reserve();
        void* entry = nullptr;
        KvObj* tombstone = nullptr;
        require(store.atomic_prepare_plain(slice(key), FlatStore::hash_key(slice(key)), 0, entry),
                "Rule P foreign version prepared");
        store.atomic_install_plain(FlatStore::hash_key(slice(key)), slice(key), entry, tombstone, last);
        store.atomic_clear_read_epoch();
        server.atomic_commit_publish();
        AtomicSurvivorsTest::publish_stale_sample(server, first);
        require(server.atomic_snapshot() == first, "completed commit left a conservative watermark");
        Client client{-1}; client.set_id(889);
        auto* state = allocate_state(server, client, 0, MultiStateKind::Execute);
        require(state != nullptr, "Rule P attempt allocated");
        state->read_only = false;
        require(multi_touch_key(*state, shard, FlatStore::hash_key(slice(key)), slice(key), false),
                "Rule P advances a quiescent watermark instead of waiting forever");
        require(server.atomic_snapshot() == last, "quiescent publication caught up");
        (void)server.atomic_commit_reserve();
        require(!server.atomic_publish_quiescent() && server.atomic_snapshot() == last,
                "Rule P cannot advance across an open commit bracket");
        server.atomic_commit_publish();
        finalize_reservations(*state, shard);
        release_records(server);
        destroy_multi_state(state);
    }
    {
        const auto key = key_on(server, 0, "txn-cancel-handler");
        require(local(server, {"LPUSH", key, "seed"}) == ":1\r\n", "collection predecessor");
        Client client{-1}; client.set_id(888);
        auto* state = allocate_state(server, client, 0, MultiStateKind::Execute);
        require(state != nullptr, "collection attempt allocated");
        Request request({"LPUSH", key, "ghost"});
        std::vector<MultiQueuedCommand> queue(1);
        require(queued_copy(request.op, queue[0]) && prepare_commands(server, *state, queue),
                "collection attempt prepared");
        initialize_multi_owner_record_refs(*state);
        Shard& shard = server.shard(0);
        require(prepare_local_write_keys(server, *state, *state->commands[0], shard,
                    server.worker_of_shard(0)), "private collection clone installed");
        multi_cancel_decision(state->decision, 0);
        // A different owner can cancel exactly here, after prepare and before
        // the collection handler's find(). It must still mutate its clone.
        state->commands[0]->op->spec->handler(shard, *state->commands[0]->op);
        shard.store().atomic_clear_read_epoch();
        require(local(server, {"LRANGE", key, "0", "-1"}) == "*1\r\n$4\r\nseed\r\n",
                "cancelled handler did not mutate the committed predecessor");
        state->doomed = true;
        finalize_reservations(*state, shard);
        complete_multi_owner_record_refs(*state, server.worker_of_shard(0));
        release_records(server);
        destroy_multi_state(state);
    }
    const auto a = key_on(server, 0, "txn-help-a"), b = key_on(server, 1, "txn-help-b");
    require(local(server, {"SET", a, "old"}) == "+OK\r\n", "help predecessor");
    MultiExecState parent;
    parent.server = &server;
    parent.decision.owner = &parent;
    ScatterRun run(server, {"MSET", a, "new", b, "new"});
    run.state->multi_child = true;
    run.state->multi_parent = &parent;
    for (uint32_t i = 0; i < run.state->nsub; ++i) {
        const int shard = run.state->groups[i].shard;
        require(xshard_execute(Task{&run.client, 0, shard, run.state}, server.shard(shard),
                run.request.op, server.worker_of_shard(shard)) == ScatterTaskResult::Complete,
                "child candidate installed");
    }
    require(run.state->epoch.load() == 0, "child is still undecided");
    require(local(server, {"GET", a}) == "$3\r\nold\r\n", "foreign read skips undecided child");
    const uint64_t ticket = server.atomic_commit_reserve();
    parent.decision.epoch.store(ticket, std::memory_order_release);
    cancel_applied_scripts(server.shard(0).store(), FlatStore::hash_key(slice(a)), slice(a));
    require(run.state->epoch.load() == ticket && !parent.decision.aborted.load(),
            "writer helps the won parent ticket into the child");
    auto& store = server.shard(0).store();
    store.atomic_set_read_context(UINT64_MAX, 91);
    auto* visible = store.find(FlatStore::hash_key(slice(a)), slice(a));
    require(visible && visible->str_value() == Slice("new", 3), "writer clone sees the helped child");
    store.atomic_clear_read_epoch();
    server.atomic_commit_publish();
    MultiDecision cancelled;
    cancelled.epoch.store(kAtomicCancelledEpoch);
    const auto before = server.atomic_snapshot();
    require(!server.atomic_commit_group_cas(cancelled.epoch, [](uint64_t) { std::abort(); }),
            "cancelled decision cannot commit");
    require(server.atomic_snapshot() > before, "lost CAS closes its reserved ticket bracket");
}

void script_apply(Server& server) {
    const auto x = key_on(server, 0, "apply-x"), y = key_on(server, 1, "apply-y");
    require(local(server, {"SET", x, "B"}) == "+OK\r\n", "seed script image");
    ScatterRun run(server, {"EVAL", "redis.call('GET',KEYS[2]); return redis.call('APPEND',KEYS[1],'S')",
                           "2", x, y});
    // PIN is already grouped by xshard_prepare; the remaining phases use the production planner.
    for (unsigned i = 0; i < run.state->nsub; i++) {
        const int s = run.state->groups[i].shard;
        require(xshard_execute(Task{&run.client, 0, s, run.state}, server.shard(s), run.request.op,
                server.worker_of_shard(s)) == ScatterTaskResult::Complete, "PIN ran");
    }
    run.state->script_cut = server.atomic_snapshot();
    run.phase(ScriptPhase::Read);
    run.phase(ScriptPhase::Run);
    uint8_t expected_access = 3;  // Exact read + staged-write bits in both builds.
#if __has_include("src/cmd/watch_modified.h")
    expected_access |= kScriptModified;  // The APPEND also changed the key.
#endif
    require(run.request.reply() == ":2\r\n" && run.state->status[0] == expected_access,
            "script produced the saved BS image from a read-modify-write");
    run.state->script_ticket = server.atomic_commit_reserve();
    run.phase(ScriptPhase::Validate);
    require(!run.state->script_conflict.load(), "initial validation succeeded");
    run.state->script_apply_after_unpin = true;
    run.phase(ScriptPhase::Unpin);
    auto& store = server.shard(0).store();
    const auto hash = FlatStore::hash_key(slice(x));
    require(store.atomic_has_script_intent(hash, slice(x)), "write intent survives UNPIN");
    require(!server.shard(1).store().atomic_has_script_intent(FlatStore::hash_key(slice(y)), slice(y)),
            "read-only intent actually released in the same UNPIN wave");
    require(local(server, {"APPEND", x, "W"}, 222) == ":2\r\n", "foreign APPEND completed in the window");
    require(store.atomic_has_record(hash, slice(x)), "intervening writer drew a version");
    run.phase(ScriptPhase::Apply);
    require(run.state->script_conflict.load() && run.state->aborted.load(), "APPLY rejects stale BS");
    require(!store.atomic_has_script_intent(hash, slice(x)), "APPLY released the retained intent");
    server.atomic_commit_publish();
    require(local(server, {"GET", x}) == "$2\r\nBW\r\n", "foreign APPEND survives rejected APPLY");
}
void watch_cycle(Server& server) {
    Client a(-1), b(-1); a.set_id(201); b.set_id(202);
    Shard first, second;
    first.init_private(&server, 0, {}, {}); second.init_private(&server, 1, {}, {});
    const Slice key("watched", 7);
    for (Shard* s : {&first, &second})
        for (Client* c : {&a, &b}) require(s->watch_add(key, c, c->watch_generation()), "WATCH armed");
    std::atomic<uint64_t> ae{0}, be{0};
    std::atomic<bool> aa{false}, ba{false};
    std::atomic<uint32_t> ar{0}, br{0};
    auto reserve = [&](Shard& s, Client& c, auto& e, auto& abort, auto& refs) {
        return s.watch_validate_and_reserve(key, &c, c.watch_generation(), &c, &e, &abort, &refs, false);
    };
    require(reserve(first, a, ae, aa, ar) && reserve(second, b, be, ba, br), "opposing first reservations");
    require(ar == 1 && br == 1 && !first.watch_write_ready(key) && !second.watch_write_ready(key),
            "both blocking reservations are live");
    require(reserve(second, a, ae, aa, ar) && reserve(first, b, be, ba, br), "opposing validation completes");
    require(ar == 2 && br == 2 && !a.watch_dirty() && !b.watch_dirty(), "read-only claims coexist cleanly");
    ae.store(1); be.store(1);
    for (Shard* s : {&first, &second}) {
        require(s->watch_write_ready(key), "decided claims release writers");
        for (Client* c : {&a, &b}) s->watch_remove(key, c, c->watch_generation());
    }
    require(ar == 0 && br == 0, "reservation references drained");
}

// Drive the real final decision in both orders around the first-owner APPLY window.
// Foreign reads must finish from immutable predecessors while the decision is open.
void post_apply_probe(Server& server) {
    for (bool commit_first : {false, true}) {
        const auto x = key_on(server, 0, commit_first ? "commit-first-x" : "writer-first-x");
        const auto y = key_on(server, 1, commit_first ? "commit-first-y" : "writer-first-y");
        require(server.worker_of_shard(0) != server.worker_of_shard(1), "two APPLY owners");
        require(local(server, {"SET", x, "B"}) == "+OK\r\n" &&
                local(server, {"SET", y, "B"}) == "+OK\r\n", "seed both APPLY owners");
        ScatterRun run(server, {"EVAL", "redis.call('APPEND',KEYS[2],'T'); return redis.call('APPEND',KEYS[1],'S')",
                               "2", x, y});
        run.phase(ScriptPhase::Pin);
        run.state->script_cut = server.atomic_snapshot();
        run.phase(ScriptPhase::Read); run.phase(ScriptPhase::Run);
        require(server.script_try_certification(), "script certification");
        run.state->script_certifier = true;
        run.state->script_ticket = server.atomic_commit_reserve();
        run.state->script_ticket_live = true;
        run.phase(ScriptPhase::Validate);
        require(!run.state->script_conflict.load(), "validation succeeded before either APPLY");
        run.state->script_apply_after_unpin = true;
        run.phase(ScriptPhase::Unpin);
        run.state->script_phase = ScriptPhase::Apply; run.state->phase = 2;
        const auto count = script_select_positions(*run.state, ScriptPhase::Apply);
        reset_groups(*run.state); build_groups(*run.state, run.state->hop2, count);
        initialize_owner_completion(*run.state);
        require(run.state->nsub == 2, "both owners must install script writes");
        require(xshard_execute(Task{&run.client, 0, 0, run.state}, server.shard(0), run.request.op,
                server.worker_of_shard(0)) == ScatterTaskResult::Complete, "first APPLY completed");
        require(!run.state->epoch.load() && server.shard(0).store().atomic_pending_entries() != 0,
                "first script image is installed and still undecided");
        require(local(server, {"GET", x}, 889) == "$1\r\nB\r\n", "foreign read completes without retry in open APPLY window");
        std::string write_reply;
        if (!commit_first) write_reply = local(server, {"APPEND", x, "W"}, 888);
        require(xshard_execute(Task{&run.client, 0, 1, run.state}, server.shard(1), run.request.op,
                server.worker_of_shard(1)) == ScatterTaskResult::Complete, "second APPLY completed");
        run.state->pending.store(1);
        Ring unused_ring;
        require(xshard_complete_script<false>(server, server.thread(server.worker_of_shard(1)), unused_ring,
                    Task{&run.client, 0, 1, run.state}, run.request.op, *run.state) == ScatterFinish::Final,
                "production script final decision");
        if (commit_first) {
            write_reply = local(server, {"APPEND", x, "W"}, 888);
            require(run.request.reply() == ":2\r\n" && write_reply == ":3\r\n" &&
                    local(server, {"GET", x}) == "$3\r\nBSW\r\n",
                    "committed script precedes foreign APPEND");
        } else {
            require(run.request.reply().starts_with("-TRYAGAIN ") && write_reply == ":2\r\n" &&
                    local(server, {"GET", x}) == "$2\r\nBW\r\n" &&
                    local(server, {"GET", y}) == "$1\r\nB\r\n",
                    "explicit key conflict rejects the whole script, with no lost write or partial success");
        }
    }
}

void mset_arity(Server& server) {
    const auto a = key_on(server, 0, "arity-a"), b = key_on(server, 1, "arity-b");
    for (const char* verb : {"MSET", "MSETNX"}) {
        Client c(-1); c.set_id(404);
        require(multi_io(server, c, {"MULTI"}) == "+OK\r\n", "fresh MULTI");
        require(multi_io(server, c, {verb, a, "one", b}) == "+QUEUED\r\n", "malformed pair list queued");
        const auto reply = multi_io(server, c, {"EXEC"});
        require(reply.starts_with("*1\r\n-ERR wrong number"), "EXEC has a command error element");
        require(local(server, {"GET", a}) == "$-1\r\n" && local(server, {"GET", b}) == "$-1\r\n",
                "malformed MSET/MSETNX changed no key");
    }
}
void watch_oom(Server& server) {
    const std::string key(128, 'w');
    unsigned failures = 0; bool saw_rollback = false, reached_success = false;
    const int max_budget = static_cast<int>(server.cfg().databases) * 8 + 64;
    for (int budget = 0; budget < max_budget; budget++) {
        Client c(-1); c.set_id(505);
        Request watch({"WATCH", key});
        MultiExecState* state = nullptr;
        allocation_failed = false; fail_new_after = budget;
        const auto action = multi_handle_io(server, c, watch.op, 0, state);
        fail_new_after = -1;
        if (allocation_failed) {
            failures++;
            require(action == MultiIoAction::LocalDone && watch.reply().starts_with("-ERR out of memory"),
                    "injected WATCH preparation failure reported");
            auto* session = c.multi_session();
            saw_rollback |= session && session->watched.capacity() != 0;
            require(!session || session->watched.empty(), "failed WATCH did not leave a phantom session key");
            watch.op.clear_reply();
            require(multi_handle_io(server, c, watch.op, 0, state) == MultiIoAction::Dispatch,
                    "successful retry posts real WATCH work");
        } else {
            require(action == MultiIoAction::Dispatch, "WATCH success reached");
            reached_success = true;
        }
        require(state && state->watched.size() == server.cfg().databases,
                "retry owns every namespace alias of one logical key");
        std::vector<bool> namespaces(server.cfg().databases, false);
        for (const auto& alias : state->watched) {
            require(alias.db == 0 && alias.key == key && alias.ns < namespaces.size() &&
                    !namespaces[alias.ns], "one exact logical key, no duplicate namespace alias");
            namespaces[alias.ns] = true;
        }
        for (const auto shard_id : state->shards)
            require(execute_watch_phase(*state, server.shard(shard_id)), "retry registered owner watcher");
        server.shard(sid(server, key)).watch_write_committed(slice(key));
        require(c.watch_dirty(), "foreign mutation dirties the successfully retried WATCH");
        for (const auto& alias : state->watched)
            server.shard(alias.shard).watch_remove(
                Slice(alias.key.data(), alias.key.size(), alias.ns), &c, c.watch_generation());
        require(c.safe_to_release(), "every alias releases its client reference");
        c.multi_session()->pending = nullptr;
        c.multi_session()->watched.clear();
        destroy_multi_state(state);
        if (reached_success) break;
    }
    require(failures >= 10 && saw_rollback && reached_success, "swept through the post-append OOM window");
}

void lua_case(Server& server, const std::string& name) {
    Shard& shard = server.shard(0);
    auto call = [&](std::vector<std::string> args) {
        Request r(std::move(args)); r.op.spec->handler(shard, r.op); return r.reply();
    };
    if (name == "closure") {
        require(call({"FUNCTION", "LOAD", "#!lua name=retained\nlocal reg=redis.register_function\n"
             "reg('retained',function() reg('late',function() return 1 end); return 42 end)"}) ==
             "$8\r\nretained\r\n", "retained closure library loaded");
        const auto reply = call({"FCALL", "retained", "0"});
        require(reply.starts_with("-") && reply.find("not available here") != std::string::npos,
                "escaped registration closure is revoked after materialization");
    } else if (name == "lua_conversion") {
        for (const char* body : {"error('conversion failed')", "while true do end"}) {
            const std::string table = std::string("setmetatable({}, {__index=function() ") + body + " end})";
            require(call({"EVAL", "return " + table, "0"}) == "*0\r\n", "reply conversion never invokes __index");
            require(call({"EVAL", "error(" + table + ")", "0"}).starts_with("-ERR"),
                    "error conversion never invokes __index");
        }
    } else if (name == "lua_lines") {
        require(call({"EVAL", "return {ok='OK\\r\\n:42'}", "0"}) == "+OK  :42\r\n", "status has exactly one frame");
        require(call({"EVAL", "return {err='ERR bad\\r\\n:42'}", "0"}) == "-ERR bad  :42\r\n", "error has exactly one frame");
    } else if (name == "library_limit") {
        for (const char* body : {"while true do end", "pcall(function() while true do end end); "
                               "redis.register_function('late',function() return 1 end)"}) {
            const auto before = function_stats().libraries;
            const auto reply = call({"FUNCTION", "LOAD", std::string("#!lua name=spin\n") + body});
            require(reply.starts_with("-") && reply.find("instruction limit") != std::string::npos,
                    "FUNCTION LOAD budget failure is terminal even when caught");
            require(function_stats().libraries == before, "timed out library was not registered");
        }
    } else if (name == "instruction_limit") {
        require(call({"EVAL", "local ok=pcall(function() while true do end end); return 42", "0"}).starts_with("-BUSY"),
                "caught instruction-limit error still fails the activation");
    }
    require(call({"EVAL", "return 7", "0"}) == ":7\r\n", "interpreter remains usable");
}
void stage_flag(Server& server) {
    static_assert(std::is_same_v<decltype(ScatterState::script_stage_limit), std::atomic<bool>>,
                  "owner tasks concurrently publish the staging-failure flag");
    const auto a = key_on(server, 0, "stage-a"), b = key_on(server, 1, "stage-b");
    const std::string big(5 * 1024 * 1024, 's');
    require(local(server, {"SET", a, big}) == "+OK\r\n", "oversized owner image seeded");
    ScatterRun run(server, {"EVAL", "return redis.call('GET',KEYS[1])", "2", a, b});
    run.state->script_cut = server.atomic_snapshot();
    run.phase(ScriptPhase::Read);
    require(run.state->script_staged_bytes > server.script_crossshard_max_bytes() &&
            run.state->script_stage_limit.load() && run.state->aborted.load(), "derived staging cap fired");
    script_engine_error_reply(run.request.op, *run.state, WorkError::Oom);
    require(run.request.reply() == "-ERR cross-shard script staging limit exceeded\r\n", "staging error retained");
}
}

#include "atomiccollapse_checks.inc"
#include "atomic_plain_checks.inc"
#include "txnorder_checks.inc"

int main(int argc, char** argv) {
    require(argc == 2, "one named regression is required");
    require(command_registry_init(false), "command registry");
    Config cfg; cfg.databases = 1;
    const std::string name = argv[1];
    if (name.starts_with("plain_")) cfg.atomic = name.ends_with("_1") ? 1 : 0;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0;
    // Exercise the fixed production instruction budget, including caught-limit failure.
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "16-shard, 6:2 owner geometry initialized");
    command_bind_server(&server);
    std::string acl_error;
    require(acl_initialize(server, cfg, acl_error), "default ACL initialized");
    if (name.starts_with("txnorder_")) txnorder_checks(server, name);
    else if (name.starts_with("plain_")) atomic_plain_checks(server, name);
    else if (name == "admission") { admission(server); atomiccollapse_checks(); }
    else if (name.starts_with("collapse_")) atomiccollapse_checks(name.substr(9));
    else if (name == "script_keys") script_keys(server);
    else if (name == "txn_intents") txn_intents(server);
    else if (name == "txn_help") txn_help(server);
    else if (name == "txn_group") txn_group(server);
    else if (name == "rename_overlay" || name == "watch_parent") rename(server, name == "watch_parent");
    else if (name == "write_latest") write_latest(server);
    else if (name == "script_apply") script_apply(server);
    else if (name == "watch_cycle") watch_cycle(server);
    else if (name == "post_apply_probe") post_apply_probe(server);
    else if (name == "mset_arity") mset_arity(server);
    else if (name == "watch_oom") watch_oom(server);
    else if (name == "stage_flag") stage_flag(server);
    else if (name == "closure" || name == "lua_conversion" || name == "lua_lines" ||
             name == "library_limit" || name == "instruction_limit") lua_case(server, name);
    else require(false, "known regression name");
    release_records(server);
    std::printf("PASS %s\n", name.c_str());
}
