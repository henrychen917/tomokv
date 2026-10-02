#pragma once
// Included before production headers by the three serverless probe callers only.
#define TOMO_PROBEADAPTER_TEST 1
#include "src/store/flatstore.h"
#include <cstdio>
#include <cstdlib>
#include <string>

namespace {
namespace probeadapter {
using Store = tomo::FlatStore;
using Result = Store::ReadLocalProbeResult;
using tomo::KvObj;
using tomo::Slice;

static void check(bool ok, const char* state, const char* failure) {
    if (!ok) {
        std::fprintf(stderr, "FAIL probeadapter %s: %s\n", state, failure);
        std::exit(1);
    }
}

struct Witness {
    const Store& store;
    unsigned entries = 0, walks = 0;
    bool resize = false;
    uint8_t database = 0;
    inline static Witness* active = nullptr;

    explicit Witness(const Store& s) : store(s) {
        if (active) std::abort();
        active = this;
        Store::test_read_local_capture_entered = [](const Store& s) {
            if (&s == &active->store) ++active->entries;
        };
        Store::test_read_local_captured = [](const Store& s) {
            if (&s != &active->store) std::abort();
            ++active->walks;
            if (!active->resize) return;
            // A real grow between slot capture and final validation. A fresh store
            // gets a bounded insertion budget; failure to enter is never a skip.
            auto& store = const_cast<Store&>(s);
            for (unsigned n = 0; n < 128 && !store.rehashing(); ++n) {
                const std::string name = "capture-grow-" + std::to_string(n);
                const Slice key(name.data(), name.size(), active->database);
                auto* value = tomo::kvobj_new_string(key, Slice("grow"));
                check(value && store.insert(Store::hash_key(key), value) == Store::InsertResult::Inserted,
                      "transition", "bounded grow insertion succeeds");
            }
        };
    }
    ~Witness() {
        Store::test_read_local_capture_entered = nullptr;
        Store::test_read_local_captured = nullptr;
        active = nullptr;
    }
};

// Compare the adapter with the authoritative capture on unchanged, serverless
// state. Independent semantic expectations below prevent two matching wrong values
// from passing. The entry witness also rejects the original independent probe.
static Store::ReadLocalProbe probe(const Store& store, uint64_t hash, Slice key,
                                   const char* state) {
    const auto capture = store.read_local_prefetch_capture(hash, key);
    Witness witness(store);
    const auto result = store.read_local_probe(hash, key);
    check(witness.entries == 1, state, "capture entered exactly once");
    const bool walked = capture.result == Result::Hit || capture.result == Result::Missing;
    check(witness.walks == unsigned(walked), state, "exact capture walk count");
    check(result.result == capture.result && result.object == capture.object &&
          result.state == capture.state, state, "exact result/object/state projection");
    check(bool(capture.slot) == walked, state, "capture retains deciding slot only after a walk");
    return result;
}

struct Fixture {
    struct Cache {
        tomo::KvBlockCache blocks;
        ~Cache() { blocks.release_all(); }
    } cache;
    Store store{64};
    const Slice key;
    const uint64_t hash;
    KvObj* object = nullptr;

    explicit Fixture(uint8_t database) : key("capture-key", 11, database), hash(Store::hash_key(key)) {
        store.set_cached_now_ms(1000);
    }
    void arm() {
        check(store.prepare_read_local(), "fixture", "read-local preparation succeeds");
        store.configure_read_local(true, {nullptr,
            [](void*, void* owner, void* p, size_t n, tomo::ReadLocalRetireSink::ReclaimFn reclaim) {
                reclaim(owner, p, n);
            }, &cache.blocks});
        object = tomo::kvobj_new_string(key, Slice("value"));
        check(object && store.insert(hash, object) == Store::InsertResult::Inserted,
              "fixture", "known Hit insertion succeeds");
        // Make state nonzero, so an adapter dropping the state cannot pass.
        { auto guard = store.read_local_table_guard(); }
    }
    void expect(const char* state, Result expected, const KvObj* object, Slice identity) {
        const auto result = probe(store, Store::hash_key(identity), identity, state);
        const uint64_t expected_state = store.read_local_enabled() ? store.read_local_state_acquire() : 0;
        check(result.result == expected && result.object == object && result.state == expected_state,
              state, "exact semantic result/object/state");
    }
};

static Store::ReadLocalPrefetchCapture transition(Fixture& f, bool adapter, uint8_t database) {
    const auto before = f.store.rehash_progress();
    const auto state = f.store.read_local_state_acquire();
    Witness witness(f.store);
    witness.resize = true;
    witness.database = database;
    Store::ReadLocalPrefetchCapture result{};
    if (adapter) {
        const auto p = f.store.read_local_probe(f.hash, f.key);
        result = {p.result, nullptr, p.object, p.state};
    } else {
        result = f.store.read_local_prefetch_capture(f.hash, f.key);
    }
    const auto after = f.store.rehash_progress();
    check(witness.entries == 1 && witness.walks == 1, "transition", "capture entered and walked exactly once");
    check(!before.old_capacity && before.current_capacity == 64 && f.store.rehashing() &&
          after.old_capacity == 64 && after.current_capacity == 128 &&
          state != f.store.read_local_state_acquire(), "transition", "real resize entered within 128 insertions");
    check(result.result == Result::Churn && !result.object && !result.slot &&
          result.state == f.store.read_local_state_acquire(),
          "transition", "invalid topology returns Churn/null/current state");
    return result;
}

static void states(uint8_t database) {
    Fixture f(database);
    f.expect("disabled", Result::Churn, nullptr, f.key);
    f.arm();
    f.expect("Hit", Result::Hit, f.object, f.key);
    f.expect("Missing", Result::Missing, nullptr, Slice("absent", 6, database));
    f.store.foreign_read_scope_open(f.hash);
    check(f.store.foreign_read_key_unsafe(f.hash), "AtomicPending", "unsafe-key window entered");
    f.expect("AtomicPending", Result::AtomicPending, nullptr, f.key);
    f.store.foreign_read_scope_close(f.hash);
    {
        auto guard = f.store.read_local_table_guard();
        check(Store::read_local_table_mutating(f.store.read_local_state_acquire()),
              "Churn", "odd topology window entered");
        f.expect("Churn", Result::Churn, nullptr, f.key);
    }
    // Independently fresh twins enter the same real grow through the adapter and
    // capture respectively. Both must report the identical changed state word.
    Fixture a(database), b(database);
    a.arm(); b.arm();
    const auto adapter = transition(a, true, database);
    const auto capture = transition(b, false, database);
    check(adapter.result == capture.result && adapter.object == capture.object && adapter.state == capture.state,
          "transition", "exact result/object/state projection across fresh twins");
    std::printf("PASS probeadapter states db=%u: disabled Hit Missing AtomicPending Churn real-resize\n", database);
}
} // namespace probeadapter
} // namespace
