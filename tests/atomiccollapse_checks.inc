// Extends the existing admission survivor row; never starts a server or worker.
// Every fixture constructs its window deterministically. Controls are generated
// from this same source and the production header by atomiccollapse_controls.py.
namespace tomo {
struct FlatStoreRegressionTest {
    static AtomicPendingState* pending(FlatStore& s) { return s.atomic_pending_; }
    static size_t versions(const FlatStore& s) { return s.atomic_version_bytes_; }
    static size_t losers(const FlatStore& s) { return s.atomic_collapse_retire_.size(); }
};
} // namespace tomo

namespace {
struct CollapseDecision {
    std::atomic<uint64_t> epoch{0};
    std::atomic<uint32_t> refs{1};
    std::atomic<bool> aborted{false};
    AtomicEntry* entry = nullptr;
};

struct CollapseFixture {
    Server& server;
    const bool armed;
    ReadLocalDeferredQueue queue;
    struct Retirement {
        CollapseFixture* fixture;
        void* owner;
        void* payload;
        ReadLocalRetireSink::ReclaimFn reclaim;
    } retired[32]{};
    unsigned deferred = 0, reclaimed = 0;
    std::atomic<uint64_t> activity{0}, intents{0};
    uint64_t promotions = 0, freed = 0, underflows = 0;
    std::unique_ptr<FlatStore> store = std::make_unique<FlatStore>(64);
    std::string key = "collapse-key";
    uint8_t ns;

    Slice k() const { return {key.data(), static_cast<uint32_t>(key.size()), ns}; }
    uint64_t hash() const { return FlatStore::hash_key(k()); }
    FlatStore& s() { return *store; }
    CollapseFixture(Server& owner, bool on, uint8_t key_ns)
        : server(owner), armed(on), ns(key_ns) {
        require(!FlatStoreRegressionTest::pending(s()), "off construction: no atomic/read-local allocation");
        require(queue.init(&server, &server.thread(server.worker_of_shard(0))), "collapse QSBR queue initialized");
        // Also bind a spy in the unarmed fixture, so a swapped selector fails
        // with an explicit sink assertion rather than an unconfigured-sink fault.
        require(s().prepare_read_local(), "collapse sink storage prepared");
        ReadLocalRetireSink sink = *queue.sink();
        sink.context = this;
        sink.available = nullptr; sink.defer_resize = nullptr;
        sink.defer = [](void* context, void* owner, void* payload, size_t size,
                        ReadLocalRetireSink::ReclaimFn reclaim) {
            auto& f = *static_cast<CollapseFixture*>(context);
            require(f.armed, "unarmed collapse: read-local sink must not be called");
            require(f.deferred < 32, "collapse retire witness capacity");
            for (unsigned i = 0; i < f.deferred; ++i)
                require(f.retired[i].payload != payload, "duplicate loser: each payload retired exactly once");
            auto& record = f.retired[f.deferred++];
            record = {&f, owner, payload, reclaim};
            f.queue.defer(&record, payload, size, [](void* context, void* p, size_t n) {
                auto& r = *static_cast<Retirement*>(context);
                require(p == r.payload, "QSBR callback: exact retired payload");
                ++r.fixture->reclaimed;
                r.reclaim(r.owner, p, n);
            });
        };
        s().configure_read_local(armed, sink);
        s().bind_atomic_state(nullptr, nullptr, &activity, &intents, nullptr, nullptr,
                              &promotions, &freed, nullptr, &underflows);
        s().set_cached_now_ms(100);
    }
    ~CollapseFixture() {
        require(queue.empty(), "fixture teardown: no callbacks may outlive store");
    }
    KvObj* value(const char* text, int64_t deadline = -1) {
        KvObj* o = kvobj_new_string(k(), Slice(text, std::strlen(text)), deadline);
        require(o != nullptr, "collapse value allocated");
        return o;
    }
    KvObj* seed() {
        KvObj* o = value("base");
        require(s().insert(hash(), o) == FlatStore::InsertResult::Inserted, "collapse predecessor seeded");
        return o;
    }
    KvObj* install(CollapseDecision& d, const char* text, uint64_t conn,
                   uint64_t epoch, bool abort = false, int64_t deadline = -1) {
        void* prepared = nullptr;
        require(s().atomic_prepare_transaction(k(), hash(), conn, &d.epoch, &d.refs,
                    &d.aborted, nullptr, prepared), "collapse transaction prepared");
        d.entry = static_cast<AtomicEntry*>(prepared);
        KvObj* o = text ? value(text, deadline) : nullptr;
        KvObj* installed = o;
        require(s().atomic_admit(k(), o), "collapse transaction admitted");
        s().atomic_install_transaction(hash(), k(), prepared, o);
        require(!prepared && !o && d.entry->linked, "collapse entry really installed and linked");
        d.epoch.store(epoch); d.aborted.store(abort);
        return installed;
    }
    void winner(const char* expected) {
        KvObj* o = s().atomic_resolve(hash(), k(), UINT64_MAX);
        require(expected ? o && o->str_value().key_eq(Slice(expected, std::strlen(expected))) : !o,
                "collapse winner: exact logical value/tombstone");
        // The existing survivor driver checks command replies; this checks the
        // same GET reply formatter against the value selected by collapse.
        Op op; op.reset();
        if (o) reply_bulk(op.sink(), o->str_value());
        else reply_null(op.sink(), op.resp3());
        const std::string reply(op.reply.data(), op.reply.size());
        require(reply == (expected ? "$" + std::to_string(std::strlen(expected)) + "\r\n" + expected + "\r\n"
                                  : "$-1\r\n"), "collapse reply: selected winner encoded exactly");
    }
    void drain() {
        for (uint32_t i = 0; i < server.nthreads(); ++i)
            server.thread(i).publish_read_local_parked(server.read_local_epoch());
        const unsigned remaining = deferred - reclaimed;
        require(queue.drain_ready() == remaining, "QSBR released pin: all retired values reclaimed");
        require(queue.empty() && reclaimed == deferred, "QSBR released pin: queue empty and callbacks complete");
    }
    void empty(unsigned entries, unsigned occurrences, size_t live_bytes) {
        const auto* p = FlatStoreRegressionTest::pending(s());
        require(p && !p->head && !p->tail && !p->live && !activity.load(),
                "collapse unlink: head/tail/live/activity all empty");
        for (const auto* head : p->conn_heads)
            require(!head, "collapse unlink: every connection chain empty");
        require(freed == entries && promotions == occurrences && !underflows &&
                !FlatStoreRegressionTest::versions(s()) && s().object_bytes() == live_bytes,
                "collapse accounting: records/promotions/version bytes/live bytes exact, no underflow");
    }
};

void collapse_boundaries(Server& server, bool armed, uint8_t ns) {
    CollapseDecision a, b;
    CollapseFixture f(server, armed, ns); f.seed();
    f.install(a, "left", 11, 5); KvObj* final = f.install(b, "last", 12, 0);
    require(!f.s().atomic_sweep(5, UINT64_MAX, 1), "floor equality: epoch equal to floor retained");
    require(!f.s().atomic_sweep(6, 4, 1), "cleanup cutoff: epoch above cutoff retained");
    require(f.s().atomic_pending_entries() == 2 && a.refs == 1 && b.refs == 1 && !f.freed,
            "blocked cutoff: no entry/ref/accounting mutation");
    require(f.s().atomic_sweep(6, 5, 1) == 1, "cleanup cutoff equality: eligible prefix reclaimed");
    auto* p = FlatStoreRegressionTest::pending(f.s());
    require(p->head == b.entry && p->tail == b.entry && !b.entry->prev && p->live == 1 &&
            a.refs == 0 && b.refs == 1 && f.freed == 1 && f.promotions == 1,
            "undecided boundary: linked suffix and its owner reference retained");
    require(!f.s().atomic_sweep(UINT64_MAX, UINT64_MAX, 1), "undecided boundary: no cleanup past epoch zero");
    b.epoch.store(6);
    require(f.s().atomic_sweep(7, 6, 1) == 1, "decided boundary: later pass completes cleanup");
    f.winner("last"); f.empty(2, 2, kvobj_size(final)); f.drain();
}

void collapse_winners(Server& server, bool armed, uint8_t ns, bool same_conn,
                      bool abort, bool boundary, bool duplicate, bool expire) {
    CollapseDecision a, b, c;
    CollapseFixture f(server, armed, ns);
    KvObj* base = f.seed();
    f.install(a, "left", 11, 5, abort, expire ? 99 : -1);
    KvObj* final = f.install(b, "last", same_conn ? 11 : 12, 4, abort);
    const size_t final_size = kvobj_size(final), final_capacity = kvobj_capacity(final);
    if (duplicate) {
        // Synthetic duplicate predecessor, charged once per occurrence. This
        // attacks the defensive unique(), without inventing a production path
        // that publishes one object twice. Both objects have equal footprints.
        require(kvobj_size(base) == kvobj_size(b.entry->parked()[0]), "duplicate fixture equal footprints");
        a.entry->parked()[0] = b.entry->parked()[0];
        kvobj_free(base);
        b.epoch.store(6); // b wins; a's predecessor appears twice in the loser list.
        a.aborted.store(true); // force the slow overlap path despite monotone tickets.
    }
    if (boundary) f.install(c, "tail", 13, 0);
    require(f.s().atomic_sweep(7, 6, 1) == 1 && f.s().atomic_cleanup_slow() == 2,
            "overlap collapse: slow winner/retire path actually entered");
    require(a.refs == 0 && b.refs == 0, "overlap collapse: each group reference released once");
    const char* expected = abort ? "base" : (same_conn || duplicate ? "last" : (expire ? nullptr : "left"));
    f.winner(expected);
    if (boundary) {
        require(f.s().atomic_pending_entries() == 1 && c.refs == 1 && c.entry->prev == nullptr,
                "overlap boundary: unselected successor remains linked");
        c.aborted.store(true);
        require(f.s().atomic_sweep(1, 0, 1) == 1, "aborted boundary: rollback ignores epoch/cutoff");
        f.winner(expected);
    }
    const auto live_bytes = expected ? final_size : 0;
    f.empty(boundary ? 3 : 2, boundary ? 3 : 2, live_bytes);
    if (duplicate)
        require(FlatStoreRegressionTest::losers(f.s()) == 1,
                "duplicate loser: unique worklist contains one owned payload");
    if (duplicate && !armed)
        require(FlatStoreRegressionTest::pending(f.s())->cached_value_bytes == final_capacity,
                "duplicate loser: direct pool contains each reclaimed value once");
    f.drain();
}

void collapse_allocation(Server& server, bool armed, uint8_t ns) {
    unsigned refusals = 0; bool complete = false;
    for (int budget = 0; budget < 12 && !complete; ++budget) {
        CollapseDecision a, b;
        CollapseFixture f(server, armed, ns); f.seed();
        f.install(a, "left", 11, 5); f.install(b, "last", 12, 4);
        const auto bytes = f.s().object_bytes();
        allocation_failed = false; fail_new_after = budget;
        const auto result = f.s().atomic_sweep(7, 6, 1);
        fail_new_after = -1;
        if (allocation_failed) {
            ++refusals;
            require(result == 0 && f.s().atomic_pending_entries() == 2 && a.refs == 1 && b.refs == 1 &&
                    f.s().object_bytes() == bytes && !f.freed && !f.promotions && !f.deferred,
                    "allocation refusal: all entries, ownership, accounting and retire state preserved");
            require(f.s().atomic_sweep(7, 6, 1) == 1, "allocation refusal: fresh retry completes");
        } else complete = true;
        f.winner("left"); f.drain();
    }
    require(refusals == 4 && complete, "allocation window: all four scratch allocations refused, then success");
}

void collapse_snapshot_teardown(Server& server, bool armed, uint8_t ns) {
    CollapseDecision a;
    CollapseFixture f(server, armed, ns); f.seed(); f.install(a, "last", 11, 5);
    require(f.s().snapshot_prepare(1, 100) == FlatStore::SnapshotWriteResult::Ready &&
            f.s().snapshot_mark(0, 100) && f.s().snapshot_active(), "snapshot refusal: capture really active");
    require(!f.s().atomic_sweep(6, 5, 1) && f.s().atomic_pending_entries() == 1 && a.refs == 1 &&
            !f.freed && !f.deferred, "snapshot refusal: eligible entry retained without reclamation");
    f.s().snapshot_cancel();
    a.epoch.store(0);
    f.drain();
    const unsigned calls = f.deferred;
    f.store.reset(); // Actual FlatStore destructor disarms before shutdown collapse.
    require(a.aborted && a.refs == 0 && f.freed == 1 && f.deferred == calls,
            "teardown: undecided record aborted and directly reclaimed after disarm, no sink callback");
}

void collapse_pinned(Server& server, bool armed, uint8_t ns) {
    CollapseDecision a;
    CollapseFixture f(server, armed, ns); KvObj* old = f.seed();
    const auto allocation = kvobj_capacity(old);
    for (uint32_t i = 0; i < server.nthreads(); ++i)
        server.thread(i).publish_read_local_parked(server.read_local_epoch());
    server.thread(0).publish_read_local_tick(server.read_local_epoch());
    f.install(a, "last", 11, 1);
    require(f.s().atomic_sweep(2, 1, 1) == 1 && f.s().atomic_cleanup_fast() == 1 &&
            f.s().atomic_cleanup_slow() == 0, "pinned collapse: committed fast path entered");
    const auto cached = FlatStoreRegressionTest::pending(f.s())->cached_value_bytes;
    if (armed) {
        require(f.deferred == 1 && f.queue.size() == 1 && cached == 0,
                "armed pinned: loser must reach QSBR sink before any storage reuse");
        require(f.queue.drain_ready() == 0 && f.reclaimed == 0 &&
                old->str_value().key_eq(Slice("base", 4)),
                "armed pinned: actual reclaim callback blocked and immutable reader bytes intact");
    } else {
        require(!f.deferred && cached == allocation,
                "unarmed pinned: direct pool reuse, no read-local sink call");
    }
    f.drain();
    require(FlatStoreRegressionTest::pending(f.s())->cached_value_bytes == allocation,
            "released pin: actual reclaim returns exact allocation to owner pool");
}

void collapse_intent(Server& server, bool armed, uint8_t ns) {
    CollapseDecision a;
    CollapseFixture f(server, armed, ns); f.seed();
    KvObj* final = f.install(a, "last", 11, 1);
    require(f.s().atomic_script_pin(f.hash(), f.k()) && f.intents == 1 && f.activity == 1,
            "intent collapse: script reservation and version share one active shard");
    require(f.s().atomic_sweep(2, 1, 1) == 1 && !f.s().atomic_pending_entries() &&
            f.s().atomic_has_script_intent(f.hash(), f.k()) && f.intents == 1 && f.activity == 1,
            "intent collapse: freeing last version preserves live reservation and activity");
    f.winner("last");
    f.s().atomic_script_unpin(f.hash(), f.k());
    require(f.intents == 0 && f.activity == 0, "intent collapse: final unpin releases activity exactly once");
    f.empty(1, 1, kvobj_size(final)); f.drain();
}

void atomiccollapse_checks(const std::string& selection = "all") {
    const auto selected = [&](const char* name) { return selection == "all" || selection == name; };
    require(selection == "all" || selection == "pinned" || selection == "boundaries" ||
            selection == "winners" || selection == "allocation" || selection == "snapshot_teardown" ||
            selection == "intent",
            "known collapse assertion group");
    for (ThreadMode mode : {ThreadMode::Fused, ThreadMode::Split}) {
        for (unsigned databases : {1u, 3u}) {
#if TOMO_SINGLE_DATABASE
            if (databases != 1) continue;
#endif
            Config cfg; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
            cfg.thread_mode = mode; cfg.databases = databases; cfg.read_local = 1;
            cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0; cfg.save.clear();
            Server server;
            require(server.prepare_boot(cfg) && server.init(cfg), "collapse serverless mode/database geometry initialized");
            const uint8_t ns = databases == 1 ? 0 : 2;
            for (bool armed : {false, true}) {
                if (selected("pinned")) collapse_pinned(server, armed, ns);
                if (selected("boundaries")) collapse_boundaries(server, armed, ns);
                if (selected("winners")) {
                    collapse_winners(server, armed, ns, false, false, false, false, false);
                    collapse_winners(server, armed, ns, true, false, false, false, false);
                    collapse_winners(server, armed, ns, false, true, false, false, false);
                    collapse_winners(server, armed, ns, false, false, true, false, false);
                    collapse_winners(server, armed, ns, false, false, false, true, false);
                    collapse_winners(server, armed, ns, false, false, false, false, true);
                }
                if (selected("allocation")) collapse_allocation(server, armed, ns);
                if (selected("snapshot_teardown")) collapse_snapshot_teardown(server, armed, ns);
                if (selected("intent")) collapse_intent(server, armed, ns);
            }
        }
    }
    std::printf("PASS atomic collapse: %s (both arms; mode/database variants exercised)\n", selection.c_str());
}
} // namespace
