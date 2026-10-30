// Deterministic collapse work and collision witnesses. No server or timer.
// Include the cold implementation to exercise its private overflow index too;
// the supplemental makefile omits that namespace's duplicate production object.
#ifndef TOMO_FLUSHFIX3_SOURCE
#define TOMO_FLUSHFIX3_SOURCE "src/store/flush.cc"
#endif
#define TOMO_STORE_REGRESSION_TEST 1
#include TOMO_FLUSHFIX3_SOURCE
#include <cstdio>
#include <map>
#include <stdexcept>
#include <string>

using namespace tomo;
static bool fail_next_new = false;
void* operator new(size_t bytes) {
    if (fail_next_new) { fail_next_new = false; throw std::bad_alloc(); }
    if (void* p = std::malloc(bytes ? bytes : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
static void need(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
}
namespace tomo {
struct FlatStoreRegressionTest {
    static void capacity(FlatStore& s, uint32_t slots) {
        need(s.alloc_table(0, slots), "allocate exact physical table");
    }
    static uint32_t occurrences(const FlatStore& s) {
        uint32_t count = 0;
        for (auto* e = s.atomic_pending_->head; e; e = e->next) count += e->count;
        return count;
    }
};
}

static void post_delete(FlatStore& s, Slice key) {
    const auto hash = FlatStore::hash_key(key);
    void* record = nullptr;
    need(s.atomic_prepare_plain(key, hash, 77, record), "prepare later occurrence");
    KvObj* value = nullptr;
    s.atomic_install_plain(hash, key, record, value, 11);
    s.atomic_finish_plain();
}

static void work_case(uint32_t later) {
    constexpr uint32_t slots = 1u << 20;
    constexpr uint32_t residents = slots / 2;
    std::atomic<uint64_t> epoch{10};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    FlatStore s;
    FlatStoreRegressionTest::capacity(s, slots);
    for (uint32_t i = 0; i < residents; ++i) {
        char key[32];
        const int n = std::snprintf(key, sizeof(key), "before:%08u", i);
        Slice k(key, n);
        need(s.insert(FlatStore::hash_key(k), kvobj_new_int(k, i)) ==
             FlatStore::InsertResult::Inserted, "seed resident");
    }
    auto* range = s.atomic_install_flush(nullptr, -1, &epoch, &aborted, &refs, 42, 0);
    need(range != nullptr, "install work range");
    // Disjoint later deletes retain actual, copied-key production records.
    // They keep the physical table at exactly 1M slots for every P.
    for (uint32_t i = 0; i < later; ++i) {
        char key[32];
        const int n = std::snprintf(key, sizeof(key), "after:%08u", i);
        post_delete(s, Slice(key, n));
    }
    need(s.capacity() == slots && s.size() == residents, "fixed populated geometry");
    need(FlatStoreRegressionTest::occurrences(s) == later, "exact later occurrences");
    need(s.atomic_flush_ready(range, 11, 10), "work range eligible");
    need(s.atomic_flush_has_post(*range), "slow collapse actually armed");
    const auto before = atomic_flush_counters.slow_work.load();
    const auto collapsed = atomic_flush_counters.slow_collapses.load();
    try {
        need(s.atomic_flush_erase(*range), "collapse allocation succeeded");
    } catch (...) {
        std::printf("WORK slots=%u residents=%u P=%u visits=%llu completed=0\n",
                    slots, residents, later,
                    (unsigned long long)(atomic_flush_counters.slow_work.load() - before));
        throw;
    }
    const uint64_t visits = atomic_flush_counters.slow_work.load() - before;
    std::printf("WORK slots=%u residents=%u P=%u visits=%llu completed=1\n",
                slots, residents, later, (unsigned long long)visits);
    need(visits >= slots + later && visits <= 96ull * (slots + later),
         "linear work envelope for the fixed-key disjoint family");
    need(atomic_flush_counters.slow_collapses.load() == collapsed + 1, "one slow collapse");
    need(s.size() == 0, "all old physical values removed");
    s.atomic_flush_release(range);
    s.atomic_shutdown_release_records();
    need(refs.load() == 0, "work range lifetime retired");
}

static void collisions() {
    uint64_t work = 0;
    constexpr unsigned count = 1024;
    FlushPostIndex index(count, work);
    std::vector<std::string> keys;
    std::vector<KvObj*> values(count, nullptr);
    std::map<std::pair<unsigned, std::string>, unsigned> first;
    keys.reserve(count);
    uint64_t random = 17;
    for (unsigned i = 0; i < count; ++i) {
        std::string key(i % 65, '\0');
        for (auto& c : key) { random = mix64(random); c = char(random); }
        if (i && i % 7 == 0) key = keys[i / 7];
        keys.push_back(std::move(key));
        Slice k(keys.back().data(), keys.back().size(), i % 16);
        first.try_emplace(std::pair(unsigned(k.ns), keys.back()), i);
        index.insert(0, k, &values[i]); // force full-hash collisions and overflow
    }
    for (unsigned i = 0; i < count; ++i) {
        Slice k(keys[i].data(), keys[i].size(), i % 16);
        need(index.find(0, k) == &values[first.at({k.ns, keys[i]})],
             "collision/prefix/NUL/namespace lookup retains first occurrence");
        need(!index.find(1, k), "full hash remains part of identity");
    }
    need(!index.find(0, Slice("missing", 7)), "missing colliding key");
    size_t unique = 0;
    index.for_each([&](KvObj**) { ++unique; });
    need(unique == first.size(), "retire each unique predecessor once");
    need(work < count * (72 + 9 * 64) * 5ull, "collision tree has a key-bit work bound");
    std::printf("PASS collision tree unique=%zu visits=%llu\n", unique, (unsigned long long)work);
}

static void allocation_failure() {
    std::atomic<uint64_t> epoch{10};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    FlatStore s;
    Slice key("old", 3);
    need(s.insert(FlatStore::hash_key(key), kvobj_new_int(key, 5)) ==
         FlatStore::InsertResult::Inserted, "OOM seed");
    auto* range = s.atomic_install_flush(nullptr, -1, &epoch, &aborted, &refs, 42, 0);
    need(range != nullptr, "OOM range");
    post_delete(s, Slice("later", 5));
    fail_next_new = true;
    need(!s.atomic_flush_erase(*range) && !fail_next_new, "scratch failure defers");
    need(s.size() == 1 && refs.load() == 1, "scratch failure leaves residents and range intact");
    need(s.atomic_flush_erase(*range) && s.size() == 0, "scratch retry completes");
    s.atomic_flush_release(range);
    s.atomic_shutdown_release_records();
    std::puts("PASS scratch OOM before mutation and successful retry");
}

static void repeated_occurrences() {
    std::atomic<uint64_t> epoch{10};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    FlatStore s;
    const Slice key("repeat", 6, kSingleDatabase ? 0 : 7);
    const auto hash = FlatStore::hash_key(key);
    need(s.insert(hash, kvobj_new_int(key, 5)) == FlatStore::InsertResult::Inserted,
         "repeated-key seed");
    auto* range = s.atomic_install_flush(nullptr, key.ns, &epoch, &aborted, &refs, 42, 0);
    need(range != nullptr, "repeated-key range");
    std::vector<AtomicEntry*> entries;
    for (unsigned i = 0; i < 5; ++i) {
        void* opaque = nullptr;
        need(s.atomic_prepare_plain(key, hash, 77, opaque), "repeated-key record");
        entries.push_back(static_cast<AtomicEntry*>(opaque));
        KvObj* value = i == 2 ? nullptr : kvobj_new_int(key, 11 + i);
        need(s.atomic_admit(key, value), "repeated-key admission");
        s.atomic_install_plain(hash, key, opaque, value, 11 + i);
        s.atomic_finish_plain();
    }
    need(s.atomic_flush_ready(range, 11, 10) && s.atomic_flush_has_post(*range),
         "repeated-key collapse armed");
    need(s.atomic_flush_erase(*range), "repeated-key collapse");
    need(!entries.front()->parked()[0], "only first predecessor loses pre-flush value");
    for (unsigned i = 1; i < entries.size(); ++i) {
        auto* predecessor = entries[i]->parked()[0];
        need(i == 3 ? predecessor == nullptr : predecessor && predecessor->int_value() == 10 + i,
             "later predecessor remains owned by its occurrence");
    }
    s.atomic_flush_release(range);
    for (unsigned i = 0; i < entries.size(); ++i) {
        auto* visible = s.atomic_resolve(hash, key, 11 + i);
        need(i == 2 ? visible == nullptr : visible && visible->int_value() == 11 + i,
             "each live post-flush cut keeps the correct value or deletion");
    }
    s.atomic_sweep(UINT64_MAX, UINT64_MAX, 1);
    need(s.size() == 1 && s.find_no_touch(hash, key)->int_value() == 15 && refs.load() == 0,
         "repeated-key final value and range lifetime");
    s.atomic_shutdown_release_records();
    std::puts("PASS repeated occurrences retire only the first predecessor");
}

static void saturated_ranges() {
    std::atomic<uint64_t> epoch{10};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    FlatStore s;
    Slice key("kept", 4);
    const auto hash = FlatStore::hash_key(key);
    need(s.insert(hash, kvobj_new_int(key, 5)) == FlatStore::InsertResult::Inserted, "range seed");
    std::vector<AtomicEntry*> ranges;
    for (unsigned i = 0; i < 600; ++i) {
        auto* range = s.atomic_install_flush(nullptr, -1, &epoch, &aborted, &refs, 42, 0);
        need(range != nullptr, "saturated range install");
        ranges.push_back(range);
        need(s.atomic_resolve(hash, key, 10) == nullptr, "range count cannot wrap on install");
    }
    for (size_t i = ranges.size(); i-- > 1;) {
        s.atomic_flush_release(ranges[i]);
        need(s.atomic_resolve(hash, key, 10) == nullptr, "saturated release cannot hide older range");
    }
    s.clear();
    s.atomic_flush_release(ranges[0]);
    need(refs.load() == 0, "all saturated range refs retired");
    std::puts("PASS 600 overlapping ranges preserve wave 10 padding layout");
}

int main(int argc, char** argv) {
    static_assert(sizeof(AtomicEntry) == 144 && sizeof(AtomicPendingState) == 1352);
    try {
        if (argc == 2) work_case(std::stoul(argv[1]));
        else {
            collisions();
            allocation_failure();
            repeated_occurrences();
            saturated_ranges();
            for (uint32_t later : {1000u, 10000u, 100000u, 1000000u}) work_case(later);
        }
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "FAIL flushfix3: %s\n", error.what());
        return 1;
    }
}
