// Serverless prebuild checks reuse L4's pinned workers, allocator audit, and live QSBR fixture.
// Including the fixture also exposes the production scatter phases; no listener or ring starts.
#define main owner_arena_original_main
#include "owner_arena_unit.cc"
#undef main
#include "src/core/io_loop.h"
#ifndef TOMO_L4_PREBUILD_THRESHOLD
#define TOMO_L4_PREBUILD_THRESHOLD 192
#endif
constexpr uint32_t kExpectedPrebuildThreshold = TOMO_L4_PREBUILD_THRESHOLD;

namespace {
struct PrebuildRequest {
    Fixture& f;
    std::vector<std::string> args;
    Op op;
    Client client{-1};
    ScatterArenaPool pool;
    ScatterState* state = nullptr;
    std::vector<KvObj*> built;
    PrebuildRequest(Fixture& fixture, std::vector<std::string> argv, bool notify = false)
        : f(fixture), args(std::move(argv)) {
        op.reset(); client.set_id(888);
        for (const auto& arg : args) require(op.push_arg(slice(arg)), "stable prebuild argv");
        op.spec = command_lookup(op.arg(0));
        if (notify) op.spec = command_notify_variant(op.spec);
        ScatterDispatch dispatch;
        f.workers[0]->call([&] {
            require(xshard_prepare(f.server, op, pool, 0, client.id(), dispatch, false, &client) ==
                    ScatterPrepare::Ready, "IO preparation produces a scatter");
        });
        state = dispatch.state;
        op.attach_scatter_state(state);
        for (unsigned i = 0; i < state->key_count; i++) {
            const auto& key = state->keys[i];
            const bool eligible = f.server.thread_mode() == ThreadMode::Fused &&
                args[0] == "MSET" && f.server.worker_of_shard(key.shard) != 0 &&
                op.arg(key.arg + 1).n > kExpectedPrebuildThreshold;
            require(bool(key.key_anchor) == eligible, "exact per-key prebuild policy");
            require(key.stable_object == key.key_anchor, "candidate owns stable identity");
            if (eligible) {
                require(arena_of(key.key_anchor) == f.workers[0]->arena &&
                        arena_of(key.key_anchor->str_data()) == f.workers[0]->arena,
                        "both header and payload born on IO");
                require(key.key_anchor->str_value() == op.arg(key.arg + 1), "IO copied exact bytes");
            }
            built.push_back(key.key_anchor);
        }
    }
    void execute() {
        for (unsigned i = 0; i < state->nsub; i++) {
            const auto sid = state->groups[i].shard;
            f.on(sid, [&] {
                require(xshard_execute(Task{&client, 0, sid, state}, f.server.shard(sid), op,
                                      f.server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                        "owner completes fragment");
                if (state->atomic_write)
                    complete_owner_record_wave(*state, f.server.worker_of_shard(sid));
            });
        }
        if (state->atomic_write && !state->aborted.load())
            state->epoch.store(f.server.atomic_commit(), std::memory_order_release);
    }
    ~PrebuildRequest() {
        f.release_records(); f.drain();
        require(state->record_refs.load() == 0, "no scatter lifetime pins remain");
        f.workers[0]->call([&] { xshard_destroy(state, pool, 0); pool.reap_deferred(); });
        op.detach_scatter_state();
    }
};

void check_value(Fixture& f, int32_t sid, const std::string& key, const std::string& value,
                 KvObj* candidate = nullptr) {
    f.on(sid, [&] {
        auto* object = f.server.shard(sid).store().find(FlatStore::hash_key(slice(key)), slice(key));
        require(object && object->str_value() == slice(value), "owner installed exact value");
        if (candidate) require(object == candidate, "owner consumed the IO object without recopying");
    });
}

void mset_policy(Fixture& f) {
    for (unsigned size : {64u, 192u, 193u, 256u, 512u, 768u, 1024u, 8193u}) {
        const auto a = f.key(f.sid_a, "pb-local-" + std::to_string(size));
        const auto b = f.key(f.sid_b, "pb-foreign-" + std::to_string(size));
        const std::string first(size, 'x'), last(size, 'y');
        PrebuildRequest r(f, {"MSET", a, first, b, first, b, last}, size == 1024);
        r.execute();
        require(!r.state->aborted.load(), "MSET commits");
        check_value(f, f.sid_a, a, first, r.built[0]);
        check_value(f, f.sid_b, b, last, r.built[2]);
    }
    const std::string big(1024, 'n');
    const auto a = f.key(f.sid_a, "pb-nx-a-"), b = f.key(f.sid_b, "pb-nx-b-");
    { PrebuildRequest nx(f, {"MSETNX", a, big, b, big}); nx.execute();
      require(!nx.state->aborted.load(), "NX succeeds on absent keys"); }
    { PrebuildRequest nx(f, {"MSETNX", a, big, b, big}); nx.execute();
      require(nx.state->aborted.load(), "NX existence failure is exercised"); }
    if (f.server.thread_mode() == ThreadMode::Fused) {
        const auto c = f.key(f.sid_b, "pb-same-shard-");
        PrebuildRequest same(f, {"MSET", b, big, c, big});
        require(same.state->nsub == 1, "foreign same-shard MSET carries its IO candidates");
        same.execute(); check_value(f, f.sid_b, c, big, same.built[1]);
    }
}

void mset_oom(Fixture& f) {
    if (f.server.thread_mode() != ThreadMode::Fused) return;
    const auto a = f.key(f.sid_b, std::string(512, 'k') + "pb-oom-a-");
    const auto b = f.key(f.sid_b, std::string(512, 'k') + "pb-oom-b-");
    const std::string value(8193, 'v');
    const size_t header = good_size(kvobj_alloc_size(a.size(), value.size(), false, Enc::Extern));
    const size_t payload = good_size(value.size());
    require(header == good_size(kvobj_alloc_size(b.size(), value.size(), false, Enc::Extern)),
            "OOM keys use same header class");
    for (bool fail_payload : {false, true}) for (unsigned occurrence : {1u, 2u}) {
        Op op; Client client{-1}; ScatterArenaPool pool; ScatterDispatch dispatch;
        const std::vector<std::string> args{"MSET", a, value, b, value};
        op.reset(); for (const auto& arg : args) require(op.push_arg(slice(arg)), "OOM argv");
        op.spec = command_lookup(op.arg(0));
        allocation_audit.start(header, payload);
        f.workers[0]->call([&] {
            audit_allocations = true; allocation_failed = false;
            fail_size = fail_payload ? payload : header; fail_occurrence = occurrence;
            require(xshard_prepare(f.server, op, pool, 0, 888, dispatch, false, &client) ==
                    ScatterPrepare::Error, "IO allocation failure rejects unpublished MSET");
            require(allocation_failed, "OOM injection actually fired");
            audit_allocations = false; fail_size = 0; fail_occurrence = 0;
        });
        allocation_audit.finish(occurrence - 1 + fail_payload, occurrence - 1);
        require(f.server.atomic_inflight() == 0 && f.server.atomic_apply_inflight() == 0,
                "IO OOM releases both atomic admission windows");
    }
}

struct SetOutcome { std::string reply, value; bool present = false, ttl_slot = false; int64_t ttl = -1; };
SetOutcome run_set(Fixture& f, const std::string& key, const std::vector<std::string>& options,
                   bool prebuild, bool notify, bool seed, bool seed_ttl) {
    const auto sid = f.sid_b;
    f.on(sid, [&] {
        f.server.shard(sid).store().erase(FlatStore::hash_key(slice(key)), slice(key));
        f.server.shard(sid).set_cached_now_ms(1000, 0);
        f.server.shard(sid).set_notify_mask(notify ? NOTIFY_KEYEVENT | NOTIFY_STRING |
                                                   NOTIFY_GENERIC | NOTIFY_NEW : 0);
        if (seed) require(xshard_store_string(f.server.shard(sid), slice(key),
                    FlatStore::hash_key(slice(key)), Slice("old", 3), seed_ttl ? 9000 : -1) ==
                    XshardStringStoreResult::Stored, "SET seed");
    });
    Op op; std::vector<std::string> args{"SET", key, std::string(1024, 'z')};
    args.insert(args.end(), options.begin(), options.end());
    op.reset(); for (const auto& arg : args) require(op.push_arg(slice(arg)), "SET argv");
    op.spec = command_lookup(op.arg(0));
    if (notify) op.spec = command_notify_variant(op.spec);
    const auto* original = op.spec;
    op.hash = FlatStore::hash_key(slice(key)); op.shard = sid;
    KvObj* candidate = nullptr;
    if (prebuild) f.workers[0]->call([&] {
        l4prebuild_prepare_set(op);
        require(op.spec != original && op.zc_ptr, "large SET selected alternate handler");
        candidate = reinterpret_cast<KvObj*>(const_cast<char*>(op.zc_ptr));
        require(arena_of(candidate) == f.workers[0]->arena &&
                arena_of(candidate->str_data()) == f.workers[0]->arena, "SET born on IO");
    });
    SetOutcome out;
    f.on(sid, [&] {
        op.spec->handler(f.server.shard(sid), op);
        require(!op.zc_ptr || op.has_notify_state(), "SET candidate always detached before reply");
        auto* object = f.server.shard(sid).store().find(op.hash, slice(key));
        out.present = object != nullptr;
        if (object) {
            KvObjRawReadBuffer raw; const auto bytes = kvobj_string_value(object, raw);
            out.value.assign(bytes.p, bytes.n); out.ttl_slot = object->has_ttl_slot();
            out.ttl = f.server.shard(sid).store().deadline(op.hash, object);
            if (prebuild && options.empty()) require(object == candidate, "SET adopts exact candidate");
        }
        out.reply.assign(op.reply.data(), op.reply.size());
        if (op.has_notify_state()) notify_discard_batch(notify_take_batch(op));
    });
    return out;
}

void set_options(Fixture& f) {
    const auto key = f.key(f.sid_b, std::string(300, 's') + "pb-set-");
    const std::vector<std::vector<std::string>> options{
        {}, {"GET"}, {"NX"}, {"XX"}, {"NX", "GET"}, {"XX", "GET"},
        {"EX", "2"}, {"PX", "23"}, {"EXAT", "7"}, {"PXAT", "1234"},
        {"PXAT", "1", "GET"}, {"KEEPTTL"}, {"KEEPTTL", "GET"},
        {"PX", "1", "PX", "99"}, {"PX", "bogus"}, {"EX", "0"},
        {"NX", "XX"}, {"KEEPTTL", "EX", "1"}, {"garbage"}, {"EX"},
        {"GET", "GET"}, {"EX", "9223372036854775807"}};
    for (bool notify : {false, true}) for (bool seed : {false, true})
        for (bool ttl : {false, true}) for (const auto& opt : options) {
            const auto expected = run_set(f, key, opt, false, notify, seed, ttl);
            const auto actual = run_set(f, key, opt, true, notify, seed, ttl);
            require(expected.reply == actual.reply && expected.present == actual.present &&
                    expected.value == actual.value && expected.ttl_slot == actual.ttl_slot &&
                    expected.ttl == actual.ttl, "SET reply/value/TTL match original handler");
        }
}

void set_oom_and_discard(Fixture& f) {
    const auto key = f.key(f.sid_b, std::string(512, 'd') + "pb-discard-");
    const std::string value(8193, 'v');
    const size_t header = good_size(kvobj_alloc_size(key.size(), value.size(), false, Enc::Extern));
    const size_t payload = good_size(value.size());
    for (unsigned failure : {0u, 1u, 2u}) {
        Op op; op.reset();
        require(op.push_arg(Slice("SET", 3)) && op.push_arg(slice(key)) && op.push_arg(slice(value)),
                "discard SET arguments");
        op.spec = g_hot_command_specs.set;
        allocation_audit.start(header, payload);
        f.workers[0]->call([&] {
            audit_allocations = true; allocation_failed = false;
            fail_size = failure == 1 ? header : failure == 2 ? payload : 0;
            fail_occurrence = failure != 0;
            l4prebuild_prepare_set(op);
            require(failure ? allocation_failed && !op.zc_ptr && op.spec == g_hot_command_specs.set
                            : op.zc_ptr != nullptr, "SET OOM keeps original owner handler");
            // Covers queue refusal and retirement after owner-side admission/prepare denial.
            l4prebuild_discard_set(op);
            require(!op.zc_ptr && op.zc_shard == -1, "unused SET candidate fully detached");
            audit_allocations = false; fail_size = 0; fail_occurrence = 0;
        });
        allocation_audit.finish(failure == 1 ? 0 : 1, failure ? 0 : 1);
    }
}

void mset_nonatomic_and_migration(Fixture& f) {
    const std::string value(1024, 'h');
    const auto a = f.key(f.sid_a, "pb-move-a-"), b = f.key(f.sid_b, "pb-move-b-");
    f.server.set_atomic_enabled(false);
    {
        PrebuildRequest r(f, {"MSET", a, value, b, value});
        require(!r.state->atomic_write, "non-atomic MSET branch entered");
        r.execute(); check_value(f, f.sid_a, a, value, r.built[0]);
        check_value(f, f.sid_b, b, value, r.built[1]);
    }
    f.server.set_atomic_enabled(true);
    // Quiesce the previous wave, transfer, and prepare again against the CURRENT owner, just
    // as the production IO/executor drains require. No owner arena is captured in the policy.
    f.move(f.sid_b, f.source, false);
    {
        PrebuildRequest r(f, {"MSET", a, value, b, value});
        r.execute(); check_value(f, f.sid_b, b, value, r.built[1]);
    }
    f.move(f.sid_b, f.destination, true);
}

void prebuilt_qsbr(Fixture& f) {
    if (!f.armed) return;
    const auto a = f.key(f.sid_a, "pb-grace-a-"), b = f.key(f.sid_b, "pb-grace-b-");
    const std::string old(1024, 'o'), fresh(1024, 'f');
    { PrebuildRequest r(f, {"MSET", a, old, b, old}); r.execute(); }
    KvObj* captured = f.find(f.sid_b, b);
    f.server.thread(5).publish_read_local_tick(f.server.read_local_epoch());
    {
        PrebuildRequest r(f, {"MSET", a, fresh, b, fresh}); r.execute();
        check_value(f, f.sid_b, b, fresh, r.built[1]);
        f.release_records();
        const auto tid = f.server.worker_of_shard(f.sid_b);
        require(!f.queues[tid].empty(), "prebuilt replacement entered QSBR");
        f.on(f.sid_b, [&] { require(f.queues[tid].drain_ready() == 0, "reader pins predecessor"); });
        require(captured->str_value() == slice(old), "reader's external bytes remain immutable");
        f.server.thread(5).publish_read_local_parked(f.server.read_local_epoch());
        f.on(f.sid_b, [&] { require(f.queues[tid].drain_ready() != 0, "release after reader exits"); });
    }
}
}

namespace tomo {
// Exercise the actual SET parser hook and its refused-post cleanup, including small/local/2s
// controls. The queues are in memory; neither IoLoop::init nor an io_uring ring is called.
struct CoreConcurrencyTest {
    static void parser(Fixture& f) {
        if (f.armed) return; // armed storage lifetime is exercised by the other directed cases
        const bool fused = f.server.thread_mode() == ThreadMode::Fused;
        IoLoop io; io.srv_ = &f.server; io.self_ = &f.server.thread(0);
        for (unsigned tid = 0; tid < 8; tid++)
            require(fused ? f.server.thread(tid).init_task_inbox_local_fused()
                          : f.server.thread(tid).init_task_inbox_local(
                                f.server.placement().ifid_threads(), f.server.placement().ex_threads()),
                    "serverless task inboxes");
        for (bool local : {false, true}) for (unsigned size : {192u, 193u, 1024u}) {
            const auto sid = local ? f.sid_a : f.sid_b;
            const auto key = f.key(sid, std::string(512, 'q') + "pb-parser-");
            const std::string value(size, 'p');
            std::string wire = "*3\r\n$3\r\nSET\r\n$" + std::to_string(key.size()) + "\r\n" +
                key + "\r\n$" + std::to_string(size) + "\r\n" + value + "\r\n";
            Client c{-1}; c.set_id(999); c.set_ifid_thread(0);
            c.set_wb_slot(f.server.thread(0).assign_wb_slot(&c));
            std::memcpy(c.rbuf(), wire.data(), wire.size()); c.commit_read(wire.size());
            auto& owner = f.server.thread(f.server.worker_of_shard(sid));
            unsigned queued = 0;
            f.workers[0]->call([&] {
                while (owner.post_task_quiet(0, Task{}, f.server.thread(0).sig())) ++queued;
                require(queued && owner.task_free_slots(0) == 0, "refusal window actually opened");
            });
            const bool eligible = fused && !local && size > kExpectedPrebuildThreshold;
            const size_t header = good_size(kvobj_alloc_size(key.size(), size, false,
                                           size > kEmbedThreshold ? Enc::Extern : Enc::Raw));
            if (eligible) allocation_audit.start(header, good_size(size));
            auto parse = [&] {
                if (fused) (void)io.parse_and_dispatch<false, kGenthreadIfidBatchOps>(&c);
                else (void)io.parse_and_dispatch<false>(&c);
            };
            f.workers[0]->call([&] { audit_allocations = eligible; parse(); audit_allocations = false; });
            require(c.rpos() == 0 && c.rob().quiesced(), "refused post leaves parser and ROB untouched");
            if (eligible) allocation_audit.finish(1, 1);
            f.on(sid, [&] {
                require(owner.drain_tasks_unmasked([](const Task&) {}) == queued, "release saturated inbox");
            });
            f.workers[0]->call(parse);
            require(c.rpos() == c.rlen() && c.rob().in_flight() == 1, "same frame posts after retry");
            auto& op = c.rob().at(0);
            require(bool(op.zc_ptr) == eligible, "parser prebuilds exactly foreign fused external SET");
            KvObj* built = reinterpret_cast<KvObj*>(const_cast<char*>(op.zc_ptr));
            f.on(sid, [&] {
                require(owner.drain_tasks_unmasked([&](const Task& task) {
                    require(task.client == &c, "correct posted client");
                    op.spec->handler(f.server.shard(sid), op);
                    op.state.store(OpState::Done, std::memory_order_release);
                }) == 1, "one task consumed");
            });
            check_value(f, sid, key, value, built);
            f.workers[0]->call([&] {
                require(c.rob().drain([](Op&) {}) == 1, "posted SET retires once");
                f.server.thread(0).release_wb_slot(c.wb_slot());
            });
        }
    }
};
}

int main(int argc, char** argv) {
    require(argc == 3, "usage: l4prebuild-unit 1s|2s read-local-0|read-local-1");
    require(command_registry_init(false), "command registry initialized");
    const bool fused = std::string(argv[1]) == "1s", armed = std::string(argv[2]) == "read-local-1";
    Fixture f(fused, armed);
    mset_policy(f); mset_oom(f); set_options(f); set_oom_and_discard(f);
    mset_nonatomic_and_migration(f); prebuilt_qsbr(f); CoreConcurrencyTest::parser(f);
    require(!l4prebuild_policy(kExpectedPrebuildThreshold) &&
            l4prebuild_policy(kExpectedPrebuildThreshold + 1), "exact policy boundary engaged");
    std::printf("PASS l4prebuild %s %s: IO arenas, sizes/owners, NX, OOM, SET options, "
                "notifications, atomic=0/1, QSBR, migration, parser retry\n",
                argv[1], argv[2]);
    return 0;
}
