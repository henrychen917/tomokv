// AT5.1/AT5.2: the audit's X(k,7), U(other,0), L(k,5) schedule.
// Real FlatStore installs/resolution/reclamation, no workers or sockets.
#include "src/store/flatstore.h"
#include <cstdio>
#include <cstdlib>

// The fixture installs copied-key records, integer strings and no intents,
// notification sink or AOF. Fail closed if it reaches an unrelated subsystem.
namespace tomo {
uint64_t xshard_atomic_key_hash(const ScatterState*, uint32_t) { std::abort(); }
Slice xshard_atomic_key_slice(const ScatterState*, uint32_t) { std::abort(); }
void atomic_shutdown_unit_intent(AtomicScriptIntent&) { std::abort(); }
void atomic_free_unit_intent(UnitRef*) { std::abort(); }
HashVal::~HashVal() { std::abort(); }
ZsetVal::~ZsetVal() { std::abort(); }
StreamVal::~StreamVal() { std::abort(); }
uint64_t stream_groups_allocation_bytes(const void*) { std::abort(); }
bool AofProducer::record_delete(Slice, uint64_t) { std::abort(); }
void notify_flat_store_emit(const FlatStore*, uint32_t, NotifyEventId, Slice) { std::abort(); }
}

using namespace tomo;
static void need(bool ok, const char* why) {
    if (!ok) {
        std::fprintf(stderr, "FAIL atomfix6: %s\n", why);
        std::exit(1);
    }
}
struct Decision {
    std::atomic<uint64_t> epoch{0};
    std::atomic<uint32_t> refs{1};
    std::atomic<bool> aborted{false};
};
static void install(FlatStore& store, Decision& d, Slice key, uint64_t conn, uint64_t ticket,
                    int value) {
    void* entry = nullptr;
    const auto hash = FlatStore::hash_key(key);
    need(store.atomic_prepare_transaction(key, hash, conn, &d.epoch, &d.refs, &d.aborted, nullptr,
                                          entry),
         "prepare record");
    KvObj* object = value < 0 ? nullptr : kvobj_new_int(key, value);
    need(store.atomic_admit(key, object), "admit value");
    store.atomic_install_transaction(hash, key, entry, object);
    store.atomic_finish_plain();
    d.epoch.store(ticket, std::memory_order_release);
}
int main() {
    unsigned cases = 0, tears = 0, lost = 0;
    for (bool armed : {false, true})
        for (bool deleted : {false, true})
            for (bool too_new : {false, true}) {
                Decision x, u, l;
                KvBlockCache cache;
                FlatStore store(64);
                store.set_cached_now_ms(100);
                if (armed) {
                    need(store.prepare_read_local(), "prepare read-local");
                    store.configure_read_local(
                        true, {nullptr,
                               [](void*, void* owner, void* p, size_t n,
                                  ReadLocalRetireSink::ReclaimFn fn) {
                                   fn(owner, p, n);  // no concurrent readers in this schedule
                               },
                               &cache});
                }
                const Slice k("key", 3, kSingleDatabase ? 0 : 7);
                const Slice other("other", 5, kSingleDatabase ? 0 : 11);
                const auto h = FlatStore::hash_key(k);
                install(store, x, k, 11, 7, deleted ? -1 : 7);
                install(store, u, other, 12, too_new ? 9 : 0, 9);
                install(store, l, k, 13, 5, 5);
                auto correct = [&] {
                    auto* v = store.atomic_resolve(h, k, 7);
                    return deleted ? v == nullptr : v && v->int_value() == 7;
                };
                need(correct(), "schedule opens with ticket 7 winning");
                need(store.atomic_pending_entries() == 3, "all three records installed");
                store.atomic_sweep(8, 7, 1);
                tears += !correct();
                u.epoch.store(9, std::memory_order_release);
                store.atomic_sweep(10, 9, 1);
                need(store.atomic_pending_entries() == 0, "decided list drains");
                lost += !correct();
                store.atomic_shutdown_release_records();
                cache.release_all();
                ++cases;
            }
    std::printf("atomfix6 collapse cases=%u torn=%u lost=%u namespace=%s\n", cases, tears, lost,
                kSingleDatabase ? "db0" : "normal");
    return tears || lost ? 1 : 0;
}
