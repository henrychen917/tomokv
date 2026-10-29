// Production range lifecycle, deterministic owner interleavings; no server.
#include "src/core/server.h"
#include <cstdio>
#include <cstdlib>
using namespace tomo;
static void need(bool b, const char* why) {
    if (!b) { std::fprintf(stderr, "FAIL flushfix2: %s\n", why); std::exit(1); }
}
int main() {
    static_assert(sizeof(AtomicEntry) == 144 && sizeof(AtomicPendingState) == 1352);
    for (bool armed : {false, true}) for (bool all : {false, true})
    for (bool abort_post : {false, true}) for (bool deleted : {false, true}) {
        struct Cache { KvBlockCache blocks; ~Cache() { blocks.release_all(); } } cache;
        Shard shard;
        auto& st = shard.store();
        shard.set_cached_now_ms(1000);
        if (armed) {
            need(st.prepare_read_local(), "prepare local");
            st.configure_read_local(true, {nullptr,
                [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn fn) {
                    fn(owner, p, n);
                }, &cache.blocks});
        }
        const Slice a("a", 1, kSingleDatabase ? 0 : 7);
        const Slice b("b", 1, kSingleDatabase ? 0 : 11);
        const auto ah = FlatStore::hash_key(a), bh = FlatStore::hash_key(b);
        need(st.insert(ah, kvobj_new_int(a, 5)) == FlatStore::InsertResult::Inserted, "seed a");
        need(st.insert(bh, kvobj_new_int(b, 5)) == FlatStore::InsertResult::Inserted, "seed b");
        need(st.atomic_script_pin(ah, a), "script PIN");
        std::atomic<uint64_t> epoch{0}, post_epoch{0};
        std::atomic<bool> aborted{false}, post_aborted{false};
        std::atomic<uint32_t> refs{0}, post_refs{1};
        auto* range = st.atomic_install_flush(nullptr, all ? -1 : a.ns, &epoch, &aborted, &refs, 42, 0);
        need(range && refs.load() == 1, "range installed with lifetime");
        need(st.atomic_resolve(ah, a, 9)->int_value() == 5, "undecided foreign reader sees base");
        st.atomic_set_read_context(9, 42);
        need(!st.atomic_resolve(ah, a, 9), "own private range");
        st.atomic_clear_read_epoch();
        epoch.store(10, std::memory_order_release);
        need(st.atomic_resolve(ah, a, 9)->int_value() == 5, "old cut keeps untracked preimage");
        need(!st.atomic_resolve(ah, a, 10), "one epoch hides preimage");
        need(st.atomic_script_changed(ah, a, 9), "R3 sees flush after PIN cut");
        need(st.atomic_needs_version(ah, a), "range forces version");
        need(!st.atomic_physical_key_visible(ah, a, 10), "physical walker hides flushed resident");
        need(st.atomic_resolved_size(9) == 2, "old size");
        const uint64_t control = !all && !kSingleDatabase ? 1 : 0;
        need(st.atomic_resolved_size(10) == control, "namespace size");
        need(!st.atomic_flush_ready(range, 10, 10), "inclusive reader floor protects base");
        need(!st.atomic_flush_ready(range, 11, 9), "cleanup cutoff protects base");
        void* entry = nullptr;
        need(st.atomic_prepare_transaction(a, ah, 77, &post_epoch, &post_refs, &post_aborted,
                                          nullptr, entry), "post record allocated");
        KvObj* value = deleted ? nullptr : kvobj_new_int(a, 8);
        need(st.atomic_admit(a, value), "post value admitted");
        st.atomic_install_transaction(ah, a, entry, value);
        st.atomic_finish_plain();
        need(st.atomic_resolve(ah, a, 9)->int_value() == 5, "post write retains old cut");
        need(st.atomic_flush_ready(range, 11, 10), "range eligible after floor");
        need(st.atomic_flush_has_post(*range), "slow collapse armed");
        st.atomic_flush_erase(*range);
        st.atomic_flush_release(range);
        need(refs.load() == 0, "range lifetime retired");
        if (abort_post) post_aborted.store(true, std::memory_order_release);
        else post_epoch.store(11, std::memory_order_release);
        st.atomic_script_unpin(ah, a);
        st.atomic_sweep(UINT64_MAX, UINT64_MAX, 1);
        auto* found = st.find_no_touch(ah, a);
        need((abort_post || deleted) ? !found : found && found->int_value() == 8,
             "aborted post write rolls back to null; committed post write survives");
        need(st.size() == control + (!abort_post && !deleted), "physical size after collapse");
        need(!control || st.find_no_touch(bh, b), "other namespace survives");
        st.atomic_shutdown_release_records();
    }
    std::puts("PASS flushfix2 range cuts, PIN OCC, namespace, post-delete, abort rollback, local poison");
}
