// Production range lifecycle, deterministic owner interleavings; no server.
#include "src/core/server.h"
#include <cstdio>
#include <cstdlib>
using namespace tomo;
static void need(bool b, const char* why) {
    if (!b) { std::fprintf(stderr, "FAIL flushfix2: %s\n", why); std::exit(1); }
}
static void aof_groups() {
    Config cfg;
    cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.shards = 16;
    cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    Server server;
    need(server.prepare_boot(cfg) && server.init(cfg), "AOF fixture geometry");
    command_bind_server(&server);
    for (bool all : {false, true}) for (bool committed : {false, true})
    for (bool legacy : {false, true}) {
        AofReplayPlan plan;
        plan.shard_count = server.nshards();
        plan.sections.resize(server.nshards());
        const Slice key("flushed", 7, kSingleDatabase ? 0 : 7);
        const Slice control("control", 7, kSingleDatabase ? 0 : 11);
        for (unsigned sid = 0; sid < server.nshards(); ++sid) {
            auto& store = server.shard(sid).store();
            store.clear();
            need(store.insert(FlatStore::hash_key(key), kvobj_new_int(key, 5)) ==
                 FlatStore::InsertResult::Inserted, "AOF seed");
            need(store.insert(FlatStore::hash_key(control), kvobj_new_int(control, 7)) ==
                 FlatStore::InsertResult::Inserted, "AOF control seed");
            auto& record = plan.sections[sid];
            record.resize(40);
            snapshot_put_u32(record.data(), 0x43524f41);
            record[4] = static_cast<uint8_t>(legacy ? AofRecordKind::Flush : AofRecordKind::GroupFlush);
            record[5] = all ? 0 : 1;
            record[7] = 1;
            snapshot_put_u32(record.data() + 12, 40u | (uint32_t(all ? 0 : key.ns) << 16));
            snapshot_put_u64(record.data() + 24, uint64_t(-1));
            snapshot_put_u64(record.data() + 32, legacy ? 0 : 41);
        }
        if (committed) plan.committed_groups.insert(41);
        std::string error;
        for (unsigned sid = 0; sid < server.nshards(); ++sid) {
            need(aof_load_shard(plan, server, server.shard(sid), error), "AOF replay flush fragment");
            auto& store = server.shard(sid).store();
            const bool applied = legacy || committed;
            need(bool(store.find_no_touch(FlatStore::hash_key(key), key)) == !applied,
                 "every flush fragment requires the same GCMT; legacy still replays");
            need(bool(store.find_no_touch(FlatStore::hash_key(control), control)) ==
                 !(applied && (all || kSingleDatabase)), "AOF namespace control");
        }
    }
    std::puts("PASS flushfix2 GroupFlush all-or-none GCMT, namespace and legacy Flush replay");
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
    aof_groups();
}
