// Real owner code and a frozen PRE registry; no listener, workers or load generator.
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main
#include "tests/txnorder_linear_oracle.inc"
#include <random>

namespace tomo {
struct TxnIndexTest {
    static size_t size(const Shard& s) { return s.watch_reservations_.size(); }
};
}
namespace {
uint64_t step = 0;
void equal(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "oracle step=%llu: %s\n", (unsigned long long)step, why); std::exit(1); }
}
struct Unit {
    std::unique_ptr<MultiExecState> exec;
    ScatterState scatter;
    TxnGroupAttempt group;
    bool grouped;
    Unit(Server& s, Client& c, bool g, uint64_t age) : grouped(g) {
        exec.reset(allocate_state(s, c, 0, MultiStateKind::Execute)); require(bool(exec), "unit allocated");
        exec->decision.age_ns = group.age_ns = age;
        scatter.server = &s; scatter.watch_refs.store(ScatterState::kGroupAttemptRef);
        scatter.group_attempt_storage = &group;
        group.arrived.resize(s.nshards());
        group.place_blockers = std::make_unique<TxnPlaceBlocker[]>(s.nshards());
    }
    auto& phase() { return grouped ? group.phase : exec->decision.phase; }
    auto& epoch() { return grouped ? scatter.epoch : exec->decision.epoch; }
    auto& aborted() { return grouped ? scatter.aborted : exec->decision.aborted; }
    auto& refs() { return grouped ? scatter.watch_refs : exec->watch_refs; }
    const void* token() { return grouped ? static_cast<void*>(&scatter) : exec.get(); }
    auto& keys() { return exec->claims[0]; }
    void unpin() { (grouped ? group.place_blockers[0] : exec->place_blockers[0]).clear(); }
    Shard::WatchReservation entry() {
        Shard::WatchReservation r{token(), &epoch(), &aborted(), &refs(), nullptr, 0, false, true};
        r.unit_kind = grouped ? 2 : 1; return r;
    }
    void started() { phase().store(TxnPhase::Executing); group.arrived[0] |= 4; exec->execution_noted[0] |= 8; }
};
struct Pair { std::unique_ptr<Unit> a, b; };
const std::array<std::string, 4> names{"index-a", "index-b", "index-c", "index-d"};
Slice key(unsigned i) { return slice(names[i % names.size()]); }
std::string owned(unsigned i) { return i == 4 ? std::string{} : database_owned_key(key(i)); }

void oracle(Server& server, uint64_t operations, uint64_t seed) {
    Shard& actual = server.shard(0);
    TxnLinearOracle linear;
    linear.init_private(&server, 0, {}, {});
    Client ca{-1}, cb{-1}; ca.set_id(9001); cb.set_id(9002);
    std::array<Client, 2> watchers{Client{-1}, Client{-1}};
    for (unsigned i = 0; i < names.size(); ++i) {
        require(actual.watch_add(key(i), &watchers[0], 0), "actual watcher");
        require(linear.watch_add(key(i), &watchers[1], 0), "linear watcher");
    }
    std::mt19937_64 random(seed);
    std::array<Pair, 48> units;
    std::array<int, 8> writers_a{}, writers_b{};
    auto finish = [&](Pair& p) {
        if (!p.a) return;
        p.a->aborted().store(true); p.b->aborted().store(true);
        p.a->unpin(); p.b->unpin();
        actual.watch_finish_unit(p.a->keys(), p.a->token());
        linear.watch_finish_unit(p.b->keys(), p.b->token());
    };
    uint64_t events[12]{};
    for (step = 0; step < operations; ++step) {
        const unsigned slot = random() % units.size(), event = random() % 12, k = random() % 5;
        auto& p = units[slot]; ++events[event];
        if (!p.a || event == 0) {
            finish(p);
            // Other units can still pin these decisions. Drop those hints before reuse.
            for (auto& q : units) if (q.a) { q.a->unpin(); q.b->unpin(); }
            const bool group = random() & 1;
            const uint64_t age = 1 + random() % 4096;
            p.a = std::make_unique<Unit>(server, ca, group, age);
            p.b = std::make_unique<Unit>(server, cb, group, age);
            // Equal ages also exercise the IO/sequence tie breakers.
            p.a->exec->decision.age_seq = p.b->exec->decision.age_seq = slot;
            p.a->group.age_seq = p.b->group.age_seq = slot;
            for (unsigned j = 0, n = 1 + random() % 3; j < n; ++j) {
                const unsigned ki = random() % 5;
                const auto mode = (random() & 1) ? TxnClaimMode::Read : TxnClaimMode::Write;
                txn_add_claim(p.a->keys(), ki == 4 ? Slice{} : key(ki), mode, ki == 4);
                txn_add_claim(p.b->keys(), ki == 4 ? Slice{} : key(ki), mode, ki == 4);
            }
        } else if (event == 1 || event == 2) {
            // Hints may select different older predecessors; compare the full predicates.
            p.a->unpin(); p.b->unpin();
            const bool a = actual.watch_place_unit(p.a->keys(), p.a->entry());
            const bool b = linear.watch_place_unit(p.b->keys(), p.b->entry());
            equal(a == b, "place answer");
            if (a && !p.a->aborted().load() && event == 2) { p.a->started(); p.b->started(); }
        } else if (event == 3) {
            p.a->aborted().store(true); p.b->aborted().store(true);
        } else if (event == 4) {
            const uint64_t ticket = 1 + step;
            p.a->epoch().store(ticket); p.b->epoch().store(ticket);
            actual.watch_finish_unit(p.a->keys(), p.a->token());
            linear.watch_finish_unit(p.b->keys(), p.b->token());
        } else if (event == 5) {
            const unsigned w = random() % 8; const uint64_t stamp = 1 + random() % 4096;
            equal(actual.watch_writer_mark(key(k), &writers_a[w], k == 4, stamp) ==
                  linear.watch_writer_mark(key(k), &writers_b[w], k == 4, stamp), "writer mark");
        } else if (event == 6) {
            const unsigned w = random() % 8;
            actual.watch_writer_unmark(key(k), &writers_a[w], k == 4);
            linear.watch_writer_unmark(key(k), &writers_b[w], k == 4);
        } else if (event == 7) {
            const unsigned w = random() % 8;
            actual.watch_writer_forget(&writers_a[w]); linear.watch_writer_forget(&writers_b[w]);
        } else if (event == 8) {
            equal(actual.watch_key_ready(owned(k), nullptr, false) ==
                  linear.watch_key_ready(owned(k), nullptr, false), "key_ready started");
            equal(actual.watch_key_ready(owned(k), p.a->token(), true) ==
                  linear.watch_key_ready(owned(k), p.b->token(), true), "key_ready all_units/self");
            equal(actual.watch_all_write_ready() == linear.watch_all_write_ready(), "whole-shard ready");
        } else if (event == 9) {
            for (auto& q : units) if (q.a) {
                q.a->exec->execution_noted[0] &= ~16u; q.b->exec->execution_noted[0] &= ~16u;
            }
            actual.watch_promote_unit_waiter(owned(k), nullptr);
            linear.watch_promote_unit_waiter(owned(k), nullptr);
            for (auto& q : units) if (q.a)
                equal((q.a->exec->execution_noted[0] & 16u) == (q.b->exec->execution_noted[0] & 16u), "promote target");
        } else if (event == 10) {
            equal(actual.watch_finalize_reservation(owned(k)) == linear.watch_finalize_reservation(owned(k)), "finalize blocking");
        } else {
            // Dirty reservations may coexist with claims and writer marks. They are
            // finalized before reusing the state, including aborted decisions.
            if (k < 4 && p.a->phase().load() == TxnPhase::Executing &&
                !p.a->epoch().load() && !p.a->aborted().load() &&
                !p.a->keys().empty() && !p.a->keys()[0].key.empty()) {
                const auto s = txn_claim_slice(p.a->keys()[0]);
                actual.watch_reserve_write(s, &ca, 0, p.a->token(), &p.a->epoch(), &p.a->aborted(), &p.a->refs());
                linear.watch_reserve_write(s, &cb, 0, p.b->token(), &p.b->epoch(), &p.b->aborted(), &p.b->refs());
            }
        }
        for (auto& q : units) if (q.a) {
            equal(q.a->epoch().load() == q.b->epoch().load(), "wound/commit epoch");
            equal(q.a->aborted().load() == q.b->aborted().load(), "abort decision");
            equal(q.a->phase().load() == q.b->phase().load(), "wound phase");
        }
        equal(watchers[0].watch_dirty() == watchers[1].watch_dirty(), "finalize dirty effects");
        watchers[0].clear_watch_dirty(); watchers[1].clear_watch_dirty();
    }
    for (auto& p : units) finish(p);
    for (auto& p : units) if (p.a) { p.a->unpin(); p.b->unpin(); }
    for (unsigned i = 0; i < 8; ++i) { actual.watch_writer_forget(&writers_a[i]); linear.watch_writer_forget(&writers_b[i]); }
    for (unsigned i = 0; i < 4; ++i) {
        actual.watch_remove(key(i), &watchers[0], 0); linear.watch_remove(key(i), &watchers[1], 0);
    }
    equal(TxnIndexTest::size(actual) == 0 && linear.watch_reservations_.empty(), "teardown drains every node");
    for (auto& p : units) if (p.a) {
        const uint32_t expected = p.a->grouped ? ScatterState::kGroupAttemptRef : 0;
        equal(p.a->refs().load() == expected && p.b->refs().load() == expected, "no lifetime refs after teardown");
    }
    for (auto n : events) require(n > 0, "every random event exercised");
    std::printf("oracle operations=%llu seed=%llu mismatches=0 namespace=%s\n",
        (unsigned long long)operations, (unsigned long long)seed, kSingleDatabase ? "db0" : "multi");
}

template<class Registry>
std::array<uint64_t, 4> complexity(Server& s, Registry& r, unsigned n) {
    Client client{-1}; std::vector<std::unique_ptr<Unit>> units;
    for (unsigned i = 0; i <= n; ++i) {
        units.emplace_back(std::make_unique<Unit>(s, client, false, i + 1));
        txn_add_claim(units.back()->keys(), key(0), TxnClaimMode::Write);
        const bool ready = r.watch_place_unit(units.back()->keys(), units.back()->entry());
        require(ready == (i == 0), "one live holder followed by waiters");
        if (i == 0) units.back()->started();
    }
    std::array<uint64_t, 4> visits{};
    auto measure = [&](unsigned i, auto fn) { registry_visits.store(0); fn(); visits[i] = registry_visits.load(); };
    units.back()->unpin();
    measure(0, [&] { require(!r.watch_place_unit(units.back()->keys(), units.back()->entry()), "tail still waits"); });
    measure(2, [&] { r.watch_promote_unit_waiter(owned(0), nullptr); });
    measure(3, [&] { require(!r.watch_key_ready(owned(0), nullptr, false), "started holder blocks writer"); });
    units[n / 2]->aborted().store(true);
    measure(1, [&] { r.watch_finish_unit(units[n / 2]->keys(), units[n / 2]->token()); });
    for (auto& u : units) { u->aborted().store(true); u->unpin(); }
    for (auto& u : units) r.watch_finish_unit(u->keys(), u->token());
    return visits;
}
void complexity_check(Server& server, bool control) {
    const char* labels[] = {"place", "finish", "promote", "key_ready"};
    std::array<uint64_t, 4> first{}, pre_first{};
    TxnLinearOracle pre; pre.init_private(&server, 0, {}, {});
    bool bounded = true;
    for (unsigned n : {16u, 256u, 4096u}) {
        const auto post = complexity(server, server.shard(0), n), before = complexity(server, pre, n);
        if (n == 16) { first = post; pre_first = before; }
        for (unsigned i = 0; i < 4; ++i) {
            std::printf("visits N=%u op=%s PRE=%llu candidate=%llu PRE_ratio=%.3f candidate_ratio=%.3f\n",
                n, labels[i], (unsigned long long)before[i], (unsigned long long)post[i],
                double(before[i]) / pre_first[i], double(post[i]) / first[i]);
            if (n == 4096 && post[i] * 10 > first[i] * 12) bounded = false;
        }
    }
    require(control || bounded, "N4096 / N16 visits <= 1.2 for every operation");
}
}
int main(int argc, char** argv) {
    require(argc >= 2, "oracle|complexity|control [1s|2s] [atomic] [operations] [seed]");
    require(command_registry_init(false), "registry init");
    Config cfg; cfg.databases=1; cfg.shards=16; cfg.even_ifid=6; cfg.even_ex=2;
    cfg.key_lb=cfg.client_lb=cfg.flip_auto=0; cfg.save.clear();
    cfg.atomic=argc>3 ? std::atoi(argv[3]) : 1;
    cfg.thread_mode=argc>2 && std::string(argv[2])=="1s" ? ThreadMode::Fused : ThreadMode::Split;
    Server server; require(server.prepare_boot(cfg)&&server.init(cfg), "serverless owner init"); command_bind_server(&server);
    const std::string mode=argv[1];
    if (mode=="oracle") oracle(server, argc>4 ? std::strtoull(argv[4],nullptr,10) : 10000000,
                              argc>5 ? std::strtoull(argv[5],nullptr,10) : 0x3700b51d7ULL);
    else if (mode=="complexity" || mode=="control") complexity_check(server, mode=="control");
    else require(false,"known test mode");
    release_records(server);
}
