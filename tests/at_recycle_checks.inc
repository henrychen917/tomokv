// Included by owner_arena_unit.cc. All store/cache inspection runs on its owning Worker.
// Real queues, participants, allocator and ownership transfers; no listener or load generator.
namespace tomo {
struct FlatStoreRegressionTest {
    static ReadLocalRetireSink sink(FlatStore& store) {
        return store.read_local_store_state_required().retire_sink;
    }
    static void reclaim(void* owner, void* object, size_t capacity) {
        FlatStore::read_local_reclaim_object(owner, object, capacity);
    }
};
}
namespace {
void recycle_assert_owner_binding(FlatStore& store, const ReadLocalRetireSink& expected) {
    const auto actual = FlatStoreRegressionTest::sink(store);
    require(actual.context == expected.context && actual.block_cache == expected.block_cache &&
            actual.defer == expected.defer && actual.available == expected.available &&
            actual.defer_resize == expected.defer_resize,
            "owner assertion: every sink binding names destination at the ownership edge");
}
struct RecycleSnapshot {
    uint64_t mallocs = 0, frees = 0;
    size_t bytes = 0;
    std::array<uint32_t, KvBlockCache::kClasses> nodes{};
    std::vector<void*> pointers;
#ifdef TOMO_AT_RECYCLE_WITNESS_ENABLED
    at_recycle::Counters witness;
#endif
};
RecycleSnapshot recycle_snapshot(Fixture& f, unsigned owner) {
    RecycleSnapshot result;
    f.workers[owner]->call([&] {
        auto& cache = *f.queues[owner].sink()->block_cache;
        size_t walked_bytes = 0;
        for (unsigned cls = 0; cls < KvBlockCache::kClasses; ++cls) {
            for (auto* b = cache.heads[cls]; b; b = b->next) {
                require(++result.nodes[cls] <= KvBlockCache::kMaxNodesPerClass,
                        "class walk respects structural node bound");
                require(kv_block_class(b->allocation) == cls, "cached block has exact class");
                require(std::find(result.pointers.begin(), result.pointers.end(), b) ==
                        result.pointers.end(), "cache pointer is resident exactly once");
                result.pointers.push_back(b); walked_bytes += b->allocation;
            }
            require(result.nodes[cls] == cache.class_nodes[cls], "class occupancy census");
        }
        require(walked_bytes == cache.bytes && cache.bytes <= KvBlockCache::kMaxBytes,
                "cache byte census and total bound");
        result.bytes = cache.bytes;
        result.mallocs = recycle_alloc.mallocs; result.frees = recycle_alloc.frees;
#ifdef TOMO_AT_RECYCLE_WITNESS_ENABLED
        result.witness = cache.witness;
        require(result.witness.takes == result.witness.hits + result.witness.misses,
                "witness accounts for every take");
        cache.witness.dump(cache, "serverless-owner");
#endif
    });
    return result;
}
void recycle_census(FlatStore& store) {
    // sallocx queries allocator metadata independently of the store's header-size arithmetic.
    size_t bytes = 0, keys = 0;
    store.for_each([&](KvObj* object) {
        ++keys; bytes += sallocx(object, 0);
        require(static_cast<Type>(object->type) == Type::String, "census fixture contains strings/integers");
        if (object->encoding() == Enc::Extern) bytes += sallocx(object->external_ptr(), 0);
    });
    require(store.object_bytes() == bytes && store.size() == keys,
            "logical object bytes agree with independent live-object census");
    require(store.accounted_bytes() == bytes + keys * FlatStore::kSlotOverheadPerKey,
            "logical accounting excludes retired and cache bytes");
}
KvObj* recycle_write(FlatStore& store, const std::string& key, const std::string& value,
                     bool integer = false) {
    auto* fresh = integer ? store.make_set_int(slice(key), 1234567) :
                           store.make_set_string(slice(key), slice(value));
    require(fresh, "replacement allocation succeeds");
    require(store.insert(FlatStore::hash_key(slice(key)), fresh) == FlatStore::InsertResult::Inserted,
            "replacement publishes");
    recycle_census(store);
    return fresh;
}
void recycle_wave(bool fused) {
    for (unsigned width : {kRobWindow / 8, kRobWindow / 2, kRobWindow}) {
        for (bool integer : {false, true}) {
            Fixture f(fused, true);
            auto key = f.key(f.sid_a, "wave-");
            const std::string value(16, 'w');
            size_t capacity = 0;
            f.on(f.sid_a, [&] {
                auto& store = f.server.shard(f.sid_a).store();
                capacity = kvobj_capacity(recycle_write(store, key, value, integer));
            });
            require(recycle_snapshot(f, f.source).bytes == 0, "fresh cache is empty");
            for (unsigned wave = 0; wave < 3; ++wave) {
                auto before = recycle_snapshot(f, f.source);
                f.on(f.sid_a, [&] {
                    auto& store = f.server.shard(f.sid_a).store();
                    for (unsigned n = 0; n < width; ++n) recycle_write(store, key, value, integer);
                    require(f.queues[f.source].size() == width, "whole W-object wave engaged");
                });
                auto after = recycle_snapshot(f, f.source);
                if (wave) {
                    require(after.mallocs == before.mallocs && before.bytes - after.bytes == width * capacity,
                            "completed W-object wave supplies all next W allocations without mallocx");
                }
                f.on(f.sid_a, [&] {
                    require(f.queues[f.source].drain_ready() == width,
                            "grace drain reclaims the complete eligible wave");
                    recycle_census(f.server.shard(f.sid_a).store());
                });
                const auto ready = recycle_snapshot(f, f.source);
#ifdef TOMO_AT_RECYCLE_WITNESS_ENABLED
                require(after.witness.takes - before.witness.takes == width &&
                        after.witness.hits - before.witness.hits == (wave ? width : 0) &&
                        after.witness.fresh - before.witness.fresh == (wave ? 0 : width) &&
                        ready.witness.admitted - after.witness.admitted == width,
                        "instrumented attempts/hits/fresh allocations/admissions agree with wave census");
#endif
                require(ready.nodes[kv_block_class(capacity)] == width && ready.bytes == width * capacity,
                        "completed W-object wave is fully cached despite one live object");
                std::printf("RECYCLE wave mode=%s kind=%s W=%u warm=%u takes=%u hits=%u misses=%u "
                            "mallocx=%llu sdallocx=%llu cache_bytes=%zu live_bytes=%zu\n",
                            fused ? "1s" : "2s", integer ? "int" : "raw", width, wave != 0, width,
                            wave ? width : 0, wave ? 0 : width,
                            (unsigned long long)(after.mallocs - before.mallocs),
                            (unsigned long long)(ready.frees - before.frees), ready.bytes, capacity);
            }
        }
    }
}
// An independent PRE-behaviour oracle for the patched PAD-A fixture. Never part of POST's
// normal suite: POST must fail this assertion, while the per-shard-cap mutant and PAD-A pass.
void recycle_pre_cap(bool fused) {
    for (unsigned width : {kRobWindow / 8, kRobWindow / 2, kRobWindow}) {
        Fixture f(fused, true);
        const auto key = f.key(f.sid_a, "pre-cap-");
        f.set(f.sid_a, key, "value");
        for (unsigned n = 0; n < width; ++n) f.set(f.sid_a, key, "value");
        f.on(f.sid_a, [&] {
            require(f.queues[f.source].size() == width && f.queues[f.source].drain_ready() == width,
                    "PRE-cap oracle engages complete reclaim wave");
        });
        const auto ready = recycle_snapshot(f, f.source);
        require(ready.pointers.size() == 1, "PRE-cap oracle admits exactly one block per wave");
        for (unsigned n = 0; n < width; ++n) f.set(f.sid_a, key, "value");
        const auto used = recycle_snapshot(f, f.source);
        require(used.mallocs - ready.mallocs == width - 1 && used.bytes == 0,
                "PRE-cap oracle has one hit and W-1 allocator misses");
        std::printf("PASS PRE-cap oracle W=%u hits=1 misses=%u\n", width, width - 1);
    }
}
void recycle_pinned(bool fused) {
    Fixture f(fused, true);
    auto key = f.key(f.sid_a, "pinned-");
    const std::string old(64, 'a'), fresh(64, 'b');
    auto* held = f.set(f.sid_a, key, old);
    f.server.thread(5).publish_read_local_tick(f.server.read_local_epoch());
    for (unsigned i = 0; i < kRobWindow; ++i) {
        require(f.set(f.sid_a, key, fresh) != held, "reader-held pointer cannot be handed out");
        f.on(f.sid_a, [&] {
            require(f.queues[f.source].drain_ready() == 0, "reader pins all reclaim batches");
            recycle_census(f.server.shard(f.sid_a).store());
        });
        require(held->str_value() == slice(old), "pinned reader retains exact bytes");
        require(recycle_snapshot(f, f.source).bytes == 0, "no admission before grace");
    }
    require(f.queues[f.source].size() == kRobWindow, "pinned retirement window really opened");
    f.server.thread(5).publish_read_local_parked(f.server.read_local_epoch());
    f.on(f.sid_a, [&] {
        require(f.queues[f.source].drain_ready() == kRobWindow, "release completes pinned grace");
    });
    auto after = recycle_snapshot(f, f.source);
    require(std::find(after.pointers.begin(), after.pointers.end(), held) != after.pointers.end(),
            "reader-held pointer enters cache only after grace");
}
void recycle_full_ring(bool fused) {
    bool engaged = false;
    for (unsigned attempt = 0; attempt < 3 && !engaged; ++attempt) {
        Fixture f(fused, true); // A failed window is re-armed on completely fresh state.
        auto key = f.key(f.sid_a, "full-");
        const std::string old(16, 'x'), fresh(16, 'y');
        auto* held = f.set(f.sid_a, key, old);
        f.server.thread(5).publish_read_local_tick(f.server.read_local_epoch());
        f.on(f.sid_a, [&] {
            auto& store = f.server.shard(f.sid_a).store();
            for (unsigned n = 0; n < ReadLocalDeferredQueue::kCapacity; ++n)
                recycle_write(store, key, fresh);
            require(f.queues[f.source].size() == ReadLocalDeferredQueue::kCapacity,
                    "retire ring is full before forced grace");
        });
        require(recycle_snapshot(f, f.source).bytes == 0, "full pinned ring has no cached blocks");
        const uint64_t epoch = f.server.read_local_epoch();
        std::atomic<bool> completed{false};
        std::thread writer([&] { f.set(f.sid_a, key, fresh); completed.store(true); });
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (f.server.read_local_epoch() == epoch && !completed.load() &&
               std::chrono::steady_clock::now() < deadline) std::this_thread::yield();
        engaged = f.server.read_local_epoch() > epoch && !completed.load();
        if (engaged) require(held->str_value() == slice(old), "full-ring forced grace keeps reader bytes");
        f.server.thread(5).publish_read_local_parked(f.server.read_local_epoch());
        writer.join();
        require(completed.load(), "forced grace resumes after reader release");
        f.drain();
        require(recycle_snapshot(f, f.source).bytes != 0, "forced grace admitted reusable blocks");
    }
    require(engaged, "bounded fresh-state attempts must engage full-ring forced grace");
}
void recycle_borrow(bool fused) {
    Fixture f(fused, true);
    auto key = f.key(f.sid_a, "borrow-");
    const std::string old(64, 'r'), fresh(64, 's');
    auto* object = f.set(f.sid_a, key, old);
    const char* retained = object->str_data();
    f.on(f.sid_a, [&] {
        f.server.shard(f.sid_a).store().borrow(retained);
        recycle_alloc.watched = object; recycle_alloc.watched_freed = false;
    });
    f.set(f.sid_a, key, fresh); f.drain();
    const auto retained_cache = recycle_snapshot(f, f.source);
    require(std::find(retained_cache.pointers.begin(), retained_cache.pointers.end(), object) ==
            retained_cache.pointers.end(), "retained borrowed pointer must not appear in cache");
    require(std::memcmp(retained, old.data(), old.size()) == 0, "borrowed pointer bytes remain retained");
    for (unsigned n = 0; n < kRobWindow; ++n) {
        require(f.set(f.sid_a, key, fresh) != object, "borrowed object cannot be reused"); f.drain();
        require(std::memcmp(retained, old.data(), old.size()) == 0, "retained bytes survive reuse churn");
    }
    f.on(f.sid_a, [&] {
        auto& store = f.server.shard(f.sid_a).store();
        require(!recycle_alloc.watched_freed, "borrowed allocation not prematurely freed");
        store.unborrow(retained);
        require(recycle_alloc.watched_freed && store.outstanding_borrows() == 0,
                "final unborrow returns retained allocation through baseline free");
        recycle_alloc.watched = nullptr; recycle_census(store);
    });
}
void recycle_bounds(bool fused) {
    Fixture f(fused, true);
    auto key = f.key(f.sid_a, "bound-");
    f.set(f.sid_a, key, "anchor");
    // Feed genuine reclaim callbacks through the real queue, with an unrelated live anchor.
    // The detached objects are unpublished test inputs, so they do not change logical bytes.
    auto feed = [&](const std::string& block_key, size_t n, unsigned count) {
        f.on(f.sid_a, [&] {
            auto& store = f.server.shard(f.sid_a).store();
            const std::string val(n, 'z');
            for (unsigned i = 0; i < count; ++i) {
                auto* o = kvobj_new_string(slice(block_key), slice(val)); require(o, "bound fixture allocation");
                f.queues[f.source].defer(&store, o, kvobj_capacity(o), &FlatStoreRegressionTest::reclaim);
            }
        });
        f.drain();
    };
    auto release = [&] {
        f.on(f.sid_a, [&] { f.queues[f.source].sink()->block_cache->release_all(); });
        require(recycle_snapshot(f, f.source).bytes == 0, "bound fixture explicit release");
    };
    feed("s", 1, KvBlockCache::kMaxNodesPerClass);
    auto full = recycle_snapshot(f, f.source);
    require(full.pointers.size() == KvBlockCache::kMaxNodesPerClass, "class cap engaged exactly");
    feed("s", 1, kRobWindow);
    auto excess = recycle_snapshot(f, f.source);
    require(excess.bytes == full.bytes && excess.frees - full.frees == kRobWindow,
            "W class-bound refusals take the baseline sized-free path");
    release();
    // Two distinct 512/1024-byte classes together exactly fill the structural byte budget.
    const std::string medium(450, 'm'), large(900, 'l');
    const size_t c1 = good_size(kvobj_alloc_size(slice(medium).identity(), 1, false, Enc::Raw));
    const size_t c2 = good_size(kvobj_alloc_size(slice(large).identity(), 1, false, Enc::Raw));
    require(c1 == 512 && c2 == 1024, "heterogeneous bound fixtures use distinct exact classes");
    const unsigned half1 = KvBlockCache::kMaxBytes / 2 / c1;
    const unsigned half2 = KvBlockCache::kMaxBytes / 2 / c2;
    feed(medium, 1, half1); feed(large, 1, half2);
    full = recycle_snapshot(f, f.source);
    require(full.bytes == KvBlockCache::kMaxBytes, "total byte cap engaged with heterogeneous classes");
    feed(medium, 1, kRobWindow);
    excess = recycle_snapshot(f, f.source);
    require(excess.bytes == full.bytes && excess.frees - full.frees == kRobWindow,
            "W byte-bound refusals take the baseline sized-free path");
    f.on(f.sid_a, [&] { recycle_census(f.server.shard(f.sid_a).store()); });
    release();
    // Impossible huge requests must be rejected before overflow; no memory is dereferenced.
    f.on(f.sid_a, [&] {
        auto& cache = *f.queues[f.source].sink()->block_cache;
        require(!cache.put(nullptr, SIZE_MAX, SIZE_MAX), "oversize arithmetic cannot admit a block");
        require(!cache.put(nullptr, sizeof(KvBlockCache::FreeBlock) - 1, SIZE_MAX), "undersize rejected");
    });
}
void recycle_shapes(bool fused) {
    Fixture f(fused, true);
    auto a = f.key(f.sid_a, "shape-a-");
    const auto sid2 = f.server.thread(f.source).shards()[1]->id();
    auto b = f.key(sid2, "shape-b-");
    for (size_t length : std::array<size_t, 9>{0, 1, 15, 16, 17,
                          kEmbedThreshold - 1, kEmbedThreshold, kEmbedThreshold + 1, 4096}) {
        for (const auto& sk : {std::pair{f.sid_a, a}, std::pair{sid2, b}}) {
            f.on(sk.first, [&] {
                recycle_write(f.server.shard(sk.first).store(), sk.second, std::string(length, 'v'));
            });
        }
        f.drain(); recycle_snapshot(f, f.source);
    }
    f.on(f.sid_a, [&] { f.queues[f.source].sink()->block_cache->release_all(); });
    auto before = recycle_snapshot(f, f.source);
    require(before.bytes == 0, "Extern predecessor fixture starts empty");
    f.on(f.sid_a, [&] { recycle_write(f.server.shard(f.sid_a).store(), a, "inline"); });
    f.drain();
    auto after = recycle_snapshot(f, f.source);
    require(after.bytes == 0 && after.frees - before.frees == 2, "Extern header and payload are freed");
    // Collection rejection uses the same callback, including the collection destructor.
    f.on(f.sid_a, [&] {
        auto& store = f.server.shard(f.sid_a).store();
        auto* o = kvobj_new_list(slice(a), new ListVal()); require(o, "collection fixture allocated");
        recycle_alloc.watched = o; recycle_alloc.watched_freed = false;
        f.queues[f.source].defer(&store, o, kvobj_capacity(o), &FlatStoreRegressionTest::reclaim);
        require(f.queues[f.source].drain_ready() == 1, "collection grace engaged");
        require(recycle_alloc.watched_freed, "collection rejected to baseline destruction");
        recycle_alloc.watched = nullptr; recycle_census(store);
    });
    require(recycle_snapshot(f, f.source).bytes == 0, "collection cache exclusion");
    // A block retired by one shard can supply its sibling on the SAME owner.
    f.set(f.sid_a, a, "inline"); f.drain();
    before = recycle_snapshot(f, f.source);
    require(before.pointers.size() == 1, "one sibling-supplied cached block");
    auto* sibling = f.set(sid2, b, "inline");
    require(sibling == before.pointers.front(), "two shards share the owner's exact-size cache");
    f.drain();
    f.on(f.sid_a, [&] { f.queues[f.source].sink()->block_cache->release_all(); });
    const auto huge_key = f.key(f.sid_a, std::string(200000, 'h'));
    f.on(f.sid_a, [&] {
        auto& store = f.server.shard(f.sid_a).store();
        auto* huge = recycle_write(store, huge_key, "h");
        require(kv_block_class(kvobj_capacity(huge)) >= KvBlockCache::kClasses,
                "huge-key object lies outside cache classes");
        recycle_alloc.watched = huge; recycle_alloc.watched_freed = false;
        recycle_write(store, huge_key, "i");
        require(f.queues[f.source].drain_ready() == 1 && recycle_alloc.watched_freed,
                "huge-key object reclaims through baseline free");
        recycle_alloc.watched = nullptr;
    });
    require(recycle_snapshot(f, f.source).bytes == 0, "huge-key block is not admitted");
}
void recycle_release(bool fused) {
    for (const std::string action : {"empty", "flush", "pressure", "oom", "shutdown"}) {
        Fixture f(fused, true);
        auto key = f.key(f.sid_a, "release-");
        f.set(f.sid_a, key, "first"); f.set(f.sid_a, key, "other"); f.drain();
        const auto before = recycle_snapshot(f, f.source);
        require(before.bytes != 0, "release test must start with cached blocks");
        f.on(f.sid_a, [&] {
            auto& store = f.server.shard(f.sid_a).store();
            if (action == "empty") {
                require(store.erase(FlatStore::hash_key(slice(key)), slice(key)), "last live key deleted");
                require(f.queues[f.source].drain_ready() == 1, "empty-shard reclaim engaged");
            } else if (action == "flush") { store.clear(); }
            else if (action == "shutdown") {
                auto* detached = kvobj_new_string(slice(key), slice(std::string("pending")));
                require(detached, "shutdown pending object allocated");
                f.queues[f.source].defer(&store, detached, kvobj_capacity(detached),
                                        &FlatStoreRegressionTest::reclaim);
                require(f.queues[f.source].size() == 1 && f.queues[f.source].drain_shutdown() == 1,
                        "shutdown drains pending retirements and the occupied cache");
            }
            else {
                const std::string large(kEmbedThreshold, 'z');
                if (action == "oom") {
                    fail_size = good_size(kvobj_alloc_size(slice(key).identity(), large.size(), false, Enc::Raw));
                    fail_occurrence = 1; allocation_failed = false;
                    auto* fresh = store.make_set_string(slice(key), slice(large));
                    require(allocation_failed && fresh, "allocator refusal releases cache then retries successfully");
                    store.discard_set_value(fresh);
                } else {
                    store.configure_maxmemory(true, 1, MaxmemoryPolicy::NoEviction, 1);
                    auto* fresh = store.make_set_string(slice(key), slice(large)); require(fresh, "pressure candidate");
                    recycle_alloc.watched = fresh; recycle_alloc.watched_freed = false;
                    require(store.insert(FlatStore::hash_key(slice(key)), fresh) == FlatStore::InsertResult::MaxmemoryOom,
                            "pressure refusal actually engaged");
                    store.discard_set_value(fresh);
                    require(recycle_alloc.watched_freed, "failed insertion frees its unpublished replacement");
                    recycle_alloc.watched = nullptr;
                    store.configure_maxmemory(false, 0, MaxmemoryPolicy::NoEviction, 1);
                }
            }
            recycle_census(store);
        });
        const auto after = recycle_snapshot(f, f.source);
        if (action == "empty") {
            require(after.bytes == before.bytes && after.frees == before.frees + 1,
                    "empty shard refuses new puts without trimming existing cache");
        } else {
            require(after.bytes == 0 && after.frees > before.frees, "release action returns occupied cache to allocator");
        }
        f.drain();
        if (action == "flush") require(recycle_snapshot(f, f.source).bytes == 0, "FLUSH retire drain cannot refill cache");
    }
}
void recycle_suite(bool fused, const std::string& selected) {
#ifdef TOMO_AT_RECYCLE_WITNESS_ENABLED
    if (selected == "witness-boundary") {
        Fixture f(fused, true);
        at_recycle::request.fetch_add(1, std::memory_order_release); f.drain();
        const auto key = f.key(f.sid_a, "witness-");
        for (unsigned n = 0; n < kRobWindow / 8; ++n) f.set(f.sid_a, key, "data");
        f.drain();
        at_recycle::request.fetch_add(1, std::memory_order_release); f.drain();
        return;
    }
#endif
    if (selected == "pre-cap") { recycle_pre_cap(fused); return; }
    bool ran = false;
    for (auto [name, run] : std::array<std::pair<const char*, void (*)(bool)>, 7>{{{"wave", recycle_wave}, {"pinned", recycle_pinned},
             {"full", recycle_full_ring}, {"borrow", recycle_borrow}, {"bounds", recycle_bounds},
             {"shapes", recycle_shapes}, {"release", recycle_release}}}) {
        if (selected != "all" && selected != name) continue;
        run(fused); ran = true; std::printf("PASS recycle %s %s\n", name, fused ? "1s" : "2s");
    }
    if (selected == "all" || selected == "migration") {
        Fixture f(fused, true); live_cache_handoff(f); ran = true;
        std::printf("PASS recycle migration %s\n", fused ? "1s" : "2s");
    }
    require(ran, "known recycle directed case");
}
}
