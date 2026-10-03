// ST1: production command handlers, no listeners, rings, workers or live data.
#include "src/core/server.h"
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <sys/resource.h>
#include <unistd.h>

namespace tomo {
static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);

static void require(bool ok, const char* claim) {
    if (!ok) { std::fprintf(stderr, "FAIL flushfix: %s\n", claim); std::exit(1); }
}

static void add(Shard& shard, Slice key) {
    auto* object = kvobj_new_string(key, Slice("v", 1));
    require(object, "seed allocation");
    require(shard.store().insert(FlatStore::hash_key(key), object) == FlatStore::InsertResult::Inserted,
            "seed insertion");
}

static void flush(Shard& shard, uint8_t db, const char* verb = "FLUSHDB") {
    Op op;
    require(op.push_arg(Slice(verb, std::strlen(verb))), "flush argument");
    op.spec = command_lookup(op.cmd_name());
    require(op.spec, "flush registered");
    op.physical_db = db;
    op.spec->handler(shard, op);
}

void flushfix_semantics() {
    require(command_registry_init(false), "registry");
    for (bool armed : {false, true}) for (bool snapshot : {false, true}) {
        struct Cache { KvBlockCache blocks; ~Cache() { blocks.release_all(); } } cache;
        Shard shard;
        shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
        shard.set_cached_now_ms(1000);
        shard.set_notify_mask(NOTIFY_SAVE);
        if (armed) {
            require(shard.store().prepare_read_local(), "arm read-local");
            shard.store().configure_read_local(true, {nullptr,
                [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn reclaim) {
                    reclaim(owner, p, n);
                }, &cache.blocks});
        }
        const uint8_t db = kSingleDatabase ? 0 : 15;
        // More than one buffer's worth in ONE home. A COUNT-limited scan is not
        // an entry limit: dropping the excess or advancing its cursor loses keys.
        unsigned seeded = 0;
        for (unsigned candidate = 0; candidate < 2000000 && seeded < 400; ++candidate) {
            char key[32];
            const int length = std::snprintf(key, sizeof(key), "collision:%u", candidate);
            Slice name(key, length, db);
            if ((mix64(FlatStore::hash_key(name)) & 1023) != 0) continue;
            add(shard, name); ++seeded;
        }
        require(seeded == 400 && shard.store().capacity() == 1024,
                "overfull scan home armed on the 1024-slot table");
        if (!kSingleDatabase) add(shard, Slice("other", 5, 0));
        if (snapshot) {
            require(shard.store().snapshot_prepare(1, 1000) == FlatStore::SnapshotWriteResult::Ready &&
                    shard.store().snapshot_mark(0, 1000), "capture armed");
            // The production scatter gate prepares preimages before cmd_flush.
            // Drain those images while retaining the active frozen table/cursor.
            shard.store().for_each([&](KvObj* o) {
                if (o->key_namespace() != db) return;
                const Slice key = o->key();
                for (unsigned retry = 0; ; ++retry) {
                    const auto ready = shard.store().snapshot_prepare_write(FlatStore::hash_key(key), key);
                    if (ready == FlatStore::SnapshotWriteResult::Ready) break;
                    require(ready == FlatStore::SnapshotWriteResult::Pending && retry < 1000,
                            "snapshot preimage progress");
                    shard.store().snapshot_progress(4096, 0);
                    if (shard.store().snapshot_take_chunk()) shard.store().snapshot_handoff_complete();
                }
            });
            require(shard.store().snapshot_active() && shard.store().snapshot_preimages() == 400,
                    "all flush preimages prepared under active capture");
        }
        flush(shard, db);
        const unsigned left = kSingleDatabase ? 0 : 1;
        require(shard.store().size() == left && shard.published_size() == left,
                "every buffered and overflow key removed, other database preserved");
        require(shard.save_changes() == 1, "one dirty change per nonempty shard");
        if (!kSingleDatabase)
            require(shard.store().find(FlatStore::hash_key(Slice("other", 5)), Slice("other", 5)),
                    "other database value remains readable");
        if (snapshot) {
            for (unsigned retry = 0; shard.store().snapshot_active() && retry < 1000; ++retry) {
                shard.store().snapshot_progress(4096, 4096);
                if (shard.store().snapshot_take_chunk()) shard.store().snapshot_handoff_complete();
            }
            require(!shard.store().snapshot_active() && !shard.store().snapshot_failed(),
                    "capture completes after flush without freed cursor");
        }
        flush(shard, 0, "FLUSHALL");
        const auto changes = shard.save_changes();
        flush(shard, db);
        require(shard.save_changes() == changes, "empty flush leaves dirty counter unchanged");
        std::printf("PASS flushfix semantics: %s armed=%d snapshot=%d\n",
                    kSingleDatabase ? "db0" : "multi", armed, snapshot);
    }
}

void flushfix_memory(bool all) {
    require(command_registry_init(false), "registry");
    Shard shard;
    shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
    shard.set_cached_now_ms(1000);
    constexpr unsigned count = 65536, key_bytes = 2048;
    const uint8_t db = kSingleDatabase ? 0 : 15;
    char key[key_bytes];
    std::memset(key, 'k', sizeof(key));
    for (unsigned i = 0; i < count; ++i) {
        std::memcpy(key, &i, sizeof(i));
        add(shard, Slice(key, sizeof(key), db));
    }
    require(shard.store().size() == count, "large keyspace fully populated");
    if (!kSingleDatabase) add(shard, Slice("sentinel", 8));
    FILE* statm = std::fopen("/proc/self/statm", "r");
    unsigned long long pages = 0;
    require(statm && std::fscanf(statm, "%llu", &pages) == 1, "read address-space size");
    std::fclose(statm);
    struct rlimit previous, cap;
    require(getrlimit(RLIMIT_AS, &previous) == 0, "read address-space limit");
    cap = previous;
    cap.rlim_cur = pages * sysconf(_SC_PAGESIZE) + 2 * 1024 * 1024;
    require(cap.rlim_cur <= cap.rlim_max && setrlimit(RLIMIT_AS, &cap) == 0, "arm RLIMIT_AS");
    std::set_terminate([] {
        constexpr char failure[] = "FAIL flushfix: FLUSHDB completes under RLIMIT_AS (uncaught allocation failure)\n";
        (void)::write(STDERR_FILENO, failure, sizeof(failure) - 1);
        std::_Exit(1);
    });
    flush(shard, db, all ? "FLUSHALL" : "FLUSHDB");
    require(setrlimit(RLIMIT_AS, &previous) == 0, "restore address-space limit");
    const unsigned left = all || kSingleDatabase ? 0 : 1;
    require(shard.store().size() == left && shard.published_size() == left,
            "FLUSHDB completes under RLIMIT_AS");
    std::printf("PASS flushfix memory: %s %s keys=%u key-bytes=%u headroom=2097152 cap=%llu\n",
                kSingleDatabase ? "db0" : "multi", all ? "FLUSHALL" : "FLUSHDB",
                count, key_bytes, static_cast<unsigned long long>(cap.rlim_cur));
}
} // namespace tomo

#if !TOMO_SINGLE_DATABASE
namespace tomo_db0 {
void flushfix_semantics();
void flushfix_memory(bool);
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string which = argv[1];
    if (which == "semantics") { tomo_db0::flushfix_semantics(); tomo::flushfix_semantics(); }
    else if (which == "memory-db0") tomo_db0::flushfix_memory(false);
    else if (which == "memory-multi") tomo::flushfix_memory(false);
    else if (which == "memory-all") tomo_db0::flushfix_memory(true);
    else return 2;
}
#endif
